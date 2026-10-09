"""Stage 1 layout-aware text extraction API. Isolated from /api/conversions."""

from __future__ import annotations

import logging
import os
from datetime import datetime

import aiofiles
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pymongo.errors import PyMongoError

from app.database import extractions_col, mongo_connect_error, utcnow
from app.models.extraction_workflow import (
    GenerateXmlRequest,
    GenerateXmlResponse,
    ScopeRequest,
    ScopeResponse,
    TemplateUploadResponse,
)
from app.models.semantic_mapping import SemanticMapRequest, SemanticMapResponse
from app.services.extraction_processor import process_extraction
from app.services.extraction_workflow import (
    ExtractionWorkflowError,
    apply_scope_to_extraction,
    build_template_record,
    parse_template_xml,
    template_storage_dir,
    validate_extraction_object_id,
)
from app.services.ir_semantic_adapter import (
    ensure_semantic_mapping_body,
    fill_back_references_from_ir,
    ir_to_semantic_mapping,
)
from app.services.llm.providers.base import LLMConfigurationError
from app.services.llm.providers.factory import is_llm_configured
from app.services.llm_semantic_mapper import SemanticMappingError, map_semantic_content
from app.services.scope_resolver import InvalidScopeError
from app.services.output_format import OutputFormatError
from app.services.xml_generator import XmlGenerationError
from app.services.xml_output_router import generate_output_xml

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 20 * 1024 * 1024))


def _oid(extraction_id: str) -> ObjectId:
    try:
        return validate_extraction_object_id(extraction_id)
    except ExtractionWorkflowError:
        raise HTTPException(status_code=400, detail="Invalid extraction id") from None
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid extraction id")


def _serialize(doc: dict, include_result: bool = False) -> dict:
    template = doc.get("template") or {}
    payload = {
        "extraction_id": str(doc["_id"]),
        "document_id": str(doc["_id"]),
        "filename": doc.get("original_filename") or doc.get("filename"),
        "original_filename": doc.get("original_filename"),
        "status": doc.get("status"),
        "progress": doc.get("progress", 0),
        "current_step": doc.get("current_step"),
        "page_count": doc.get("page_count"),
        "requires_ocr": doc.get("requires_ocr"),
        "ocr_applied": doc.get("ocr_applied", False),
        "error_message": doc.get("error_message"),
        "created_at": doc.get("created_at"),
        "completed_at": doc.get("completed_at"),
        "scope": doc.get("scope", "full"),
        "template_id": template.get("template_id"),
    }
    if include_result:
        payload["result"] = doc.get("result")
    return payload


def _require_completed_extraction(doc: dict) -> None:
    if doc.get("status") == "failed":
        raise HTTPException(
            status_code=400,
            detail=doc.get("error_message") or "Extraction failed",
        )
    if doc.get("status") != "completed" or not doc.get("result"):
        raise HTTPException(status_code=409, detail="Extraction is not complete")


@router.post("")
@router.post("/")
async def start_extraction(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    skip_tables_figures: bool = Form(False),
):
    """Save the PDF for extraction only. Does not create a conversions record."""
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds {MAX_FILE_SIZE / 1024 / 1024:.0f}MB limit",
        )
    if file_size == 0:
        raise HTTPException(status_code=400, detail="PDF file is empty")

    extract_dir = os.path.join(UPLOAD_DIR, "extractions")
    os.makedirs(extract_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{os.path.basename(filename)}"
    file_path = os.path.join(extract_dir, safe_name)

    async with aiofiles.open(file_path, "wb") as out_file:
        await out_file.write(content)

    doc = {
        "filename": safe_name,
        "original_filename": filename,
        "file_path": file_path,
        "file_size": round(file_size / (1024 * 1024), 2),
        "status": "queued",
        "progress": 0,
        "current_step": "Queued",
        "result": None,
        "page_count": None,
        "requires_ocr": None,
        "ocr_applied": False,
        "error_message": None,
        "created_at": utcnow(),
        "completed_at": None,
        "scope": "full",
        "template": None,
        "skip_tables_figures": skip_tables_figures,
    }
    try:
        inserted = extractions_col().insert_one(doc)
    except PyMongoError as exc:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))

    extraction_id = str(inserted.inserted_id)
    background_tasks.add_task(process_extraction, extraction_id, file_path, filename)
    return {
        "extraction_id": extraction_id,
        "status": "queued",
        "filename": filename,
        "message": "Extraction started",
    }


@router.get("/{extraction_id}")
async def get_extraction(extraction_id: str):
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return _serialize(doc, include_result=False)


@router.get("/{extraction_id}/text")
async def get_extraction_text(extraction_id: str):
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _require_completed_extraction(doc)
    return doc["result"]


@router.get("/{extraction_id}/phase1")
async def get_extraction_phase1(extraction_id: str):
    """Phase 1 normalized document IR (no LLM). Inspect before semantic mapping."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _require_completed_extraction(doc)
    phase1 = doc.get("phase1") or (doc.get("result") or {}).get("phase1")
    if not phase1:
        raise HTTPException(status_code=404, detail="Phase 1 document not available for this extraction")
    debug_paths = doc.get("phase1_debug_paths")
    return {"phase1": phase1, "debug_artifact_paths": debug_paths}


@router.post("/{extraction_id}/template", response_model=TemplateUploadResponse)
async def upload_extraction_template(
    extraction_id: str,
    file: UploadFile = File(...),
):
    """Upload and parse an XML template for a completed extraction."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")

    filename = file.filename or "template.xml"
    if not filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Only XML template files are allowed")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Template XML file is empty")

    storage_dir = template_storage_dir(extraction_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{os.path.basename(filename)}"
    file_path = storage_dir / safe_name

    async with aiofiles.open(file_path, "wb") as out_file:
        await out_file.write(content)

    try:
        schema = parse_template_xml(file_path)
    except ExtractionWorkflowError as exc:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    template_record = build_template_record(
        template_path=file_path,
        original_filename=filename,
        schema=schema,
    )

    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {"$set": {"template": template_record}},
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))

    return TemplateUploadResponse(
        document_id=extraction_id,
        template_id=template_record["template_id"],
        original_filename=filename,
        created_at=template_record["created_at"],
        template_schema=schema,
    )


@router.post("/{extraction_id}/scope", response_model=ScopeResponse)
async def apply_extraction_scope(extraction_id: str, body: ScopeRequest):
    """Apply a scope instruction and return filtered IR + template schema."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _require_completed_extraction(doc)

    try:
        scope_result = apply_scope_to_extraction(
            scope=body.scope,
            result=doc["result"],
            template_schema=(doc.get("template") or {}).get("template_schema"),
        )
    except InvalidScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExtractionWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_scope = scope_result["resolved_scope"]
    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {"$set": {"scope": resolved_scope}},
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))

    template_schema = scope_result.get("filtered_template_schema")
    has_template = bool((doc.get("template") or {}).get("template_schema"))
    return ScopeResponse(
        document_id=extraction_id,
        scope=resolved_scope,
        allowed_sections=scope_result["allowed_sections"],
        filtered_ir=scope_result["filtered_ir"],
        filtered_template_schema=template_schema if has_template else None,
        dropped_element_count=scope_result.get("dropped_element_count", 0),
        warnings=scope_result.get("warnings", []),
    )


@router.post("/{extraction_id}/semantic-map", response_model=SemanticMapResponse)
async def semantic_map_extraction(extraction_id: str, body: SemanticMapRequest):
    """Run LLM semantic mapping on scoped IR + uploaded template schema."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _require_completed_extraction(doc)

    template = doc.get("template") or {}
    template_schema = template.get("template_schema")
    if not template_schema:
        raise HTTPException(
            status_code=400,
            detail="No template uploaded for this document. Upload a template via POST /template first.",
        )

    try:
        scope_result = apply_scope_to_extraction(
            scope=body.scope,
            result=doc["result"],
            template_schema=template_schema,
        )
    except InvalidScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExtractionWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_scope = scope_result["resolved_scope"]
    filtered_ir = scope_result["filtered_ir"]
    filtered_template_schema = scope_result["filtered_template_schema"]

    try:
        mapping_result = map_semantic_content(
            document_id=extraction_id,
            scope=resolved_scope,
            ir=filtered_ir,
            template_schema=filtered_template_schema,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SemanticMappingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    semantic_record = mapping_result.model_dump(mode="json")
    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "scope": resolved_scope,
                    "semantic_mapping": semantic_record,
                }
            },
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))

    return SemanticMapResponse(
        document_id=extraction_id,
        scope=mapping_result.scope,
        prompt_version=mapping_result.prompt_version,
        mapping=mapping_result.mapping,
        unmapped_content=mapping_result.unmapped_content,
        warnings=mapping_result.warnings,
    )


@router.post("/{extraction_id}/generate-xml", response_model=GenerateXmlResponse)
async def generate_extraction_xml(extraction_id: str, body: GenerateXmlRequest):
    """Generate XML from scoped IR + uploaded template (JATS article or DocBook book)."""
    logger.info(
        "generate-xml started for %s (use_llm=%s, llm_fallback=%s, scope=%s, output_format=%s)",
        extraction_id,
        body.use_llm,
        body.llm_fallback,
        body.scope,
        body.output_format,
    )
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _require_completed_extraction(doc)

    template = doc.get("template") or {}
    template_schema = template.get("template_schema")
    template_path = template.get("file_path")
    if not template_schema or not template_path:
        raise HTTPException(
            status_code=400,
            detail="No template uploaded for this document. Upload a template via POST /template first.",
        )
    if not os.path.exists(template_path):
        raise HTTPException(status_code=400, detail="Template file is missing on disk. Re-upload the template.")

    try:
        scope_result = apply_scope_to_extraction(
            scope=body.scope,
            result=doc["result"],
            template_schema=template_schema,
        )
    except InvalidScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ExtractionWorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    resolved_scope = scope_result["resolved_scope"]
    filtered_ir = scope_result["filtered_ir"]
    warnings: list[str] = []
    mapping_source = "ir_adapter"
    prompt_version: str | None = None
    unmapped_count = 0
    use_llm = body.use_llm
    if use_llm and not is_llm_configured():
        logger.warning(
            "LLM not configured for %s; using heuristic IR adapter (no API key)",
            extraction_id,
        )
        use_llm = False
        warnings.append("LLM not configured. Using heuristic IR adapter.")

    if use_llm:
        try:
            mapping_result = map_semantic_content(
                document_id=extraction_id,
                scope=resolved_scope,
                ir=filtered_ir,
                template_schema=scope_result["filtered_template_schema"],
                max_retries=1 if body.llm_fallback else 2,
            )
            semantic_record = mapping_result.model_dump(mode="json")
            mapping_body = mapping_result.mapping
            mapping_source = "llm"
            prompt_version = mapping_result.prompt_version
            warnings.extend(mapping_result.warnings)
            unmapped_count = len(mapping_result.unmapped_content)
            try:
                extractions_col().update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"scope": resolved_scope, "semantic_mapping": semantic_record}},
                )
            except PyMongoError as exc:
                raise HTTPException(status_code=503, detail=mongo_connect_error(exc))
        except LLMConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except SemanticMappingError as exc:
            if not body.llm_fallback:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            logger.info(
                "LLM mapping failed for %s; falling back to IR adapter: %s",
                extraction_id,
                exc,
            )
            mapping_body = ir_to_semantic_mapping(filtered_ir)
            mapping_source = "ir_adapter_fallback"
            warnings.append(
                "LLM mapping failed (Claude timeout or API error). "
                "XML was generated using deterministic extraction instead."
            )
    else:
        cached = doc.get("semantic_mapping")
        if cached and cached.get("mapping"):
            mapping_body = cached["mapping"]
            mapping_source = "cached_llm" if cached.get("prompt_version") else "cached"
            prompt_version = cached.get("prompt_version")
            warnings.extend(cached.get("warnings") or [])
            unmapped_count = len(cached.get("unmapped_content") or [])
        else:
            mapping_body = ir_to_semantic_mapping(filtered_ir)
            warnings.append("Generated using deterministic IR adapter (no LLM). Set use_llm=true for template-aware LLM mapping.")

    mapping_body = ensure_semantic_mapping_body(mapping_body)
    mapping_body = fill_back_references_from_ir(mapping_body, filtered_ir)

    try:
        xml_content, resolved_output_format = generate_output_xml(
            template_path,
            template_schema,
            mapping_body,
            output_format=body.output_format,
        )
    except OutputFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except XmlGenerationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if resolved_output_format == "docbook_5":
        warnings.append(
            "DocBook output preserves the uploaded book template structure; "
            "PDF chapter merge is not applied on this path."
        )

    generated_record = {
        "scope": resolved_scope,
        "mapping_source": mapping_source,
        "prompt_version": prompt_version,
        "output_format": resolved_output_format,
        "xml_content": xml_content,
        "warnings": warnings,
        "generated_at": utcnow(),
    }
    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {"$set": {"scope": resolved_scope, "generated_xml": generated_record}},
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))

    return GenerateXmlResponse(
        document_id=extraction_id,
        scope=resolved_scope,
        mapping_source=mapping_source,
        prompt_version=prompt_version,
        output_format=resolved_output_format,
        xml_content=xml_content,
        warnings=warnings,
        unmapped_content_count=unmapped_count,
    )


@router.get("/{extraction_id}/download-xml")
async def download_extraction_xml(extraction_id: str):
    """Download the last generated JATS XML for an extraction."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")

    generated = doc.get("generated_xml") or {}
    xml_content = generated.get("xml_content")
    if not xml_content:
        raise HTTPException(
            status_code=404,
            detail="No generated XML found. Call POST /generate-xml first.",
        )

    filename = (doc.get("original_filename") or doc.get("filename") or "document.pdf").replace(
        ".pdf", ".xml"
    )
    from fastapi.responses import Response

    xml_bytes = xml_content.lstrip("\ufeff").encode("utf-8")
    return Response(
        content=xml_bytes,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
