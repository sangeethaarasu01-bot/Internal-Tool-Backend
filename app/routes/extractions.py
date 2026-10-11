"""Stage 1 layout-aware text extraction API. Isolated from /api/conversions."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime

import aiofiles
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pymongo.errors import PyMongoError

from app.database import extractions_col, mongo_user_error, utcnow
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
from app.services.phase1_reference_bridge import merge_phase1_references_into_ir
from app.services.llm.providers.base import LLMConfigurationError
from app.services.llm_semantic_mapper import SemanticMappingError, map_semantic_content
from app.services.mapping_orchestration import (
    finalize_mapping_for_xml,
    resolve_semantic_mapping_for_generate_xml,
)
from app.services.scope_resolver import InvalidScopeError
from app.services.docbook_template_from_source import build_docbook_template_xml_from_phase1
from app.services.docbook_book_storage import (
    STORAGE_MODE_CHUNKED,
    generated_xml_record_for_chunked_book,
    persist_full_book_xml_file,
    reassemble_stored_book,
    write_book_chunks,
)
from app.services.docbook_book_chunking import DocBookChunkingError
from app.services.identity_gates import (
    IdentityMismatchError,
    log_processing_stage,
    verify_post_generation_identity,
    verify_pre_generation_identity,
)
from app.services.output_naming import safe_output_xml_filename
from app.services.source_identity import build_source_identity_from_extraction_doc
from app.services.source_identity import build_template_identity
from app.utils.hashing import sha256_file
from app.services.generate_xml_guards import (
    JatsArticleRequiredError,
    JatsTransformTooLargeError,
    assert_jats_article_template_root,
    assert_jats_transform_payload_under_limit,
    is_jats_article_required_message,
)
from app.services.output_format import OUTPUT_DOCBOOK_5, OUTPUT_IEEE_JATS, OutputFormatError, resolve_output_format
from app.services.xml_generator import XmlGenerationError
from app.services.xml_output_router import generate_output_xml
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")


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
    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds {settings.MAX_FILE_SIZE / 1024 / 1024:.0f}MB limit",
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

    source_pdf_sha256 = sha256_file(file_path)

    doc = {
        "filename": safe_name,
        "original_filename": filename,
        "file_path": file_path,
        "source_pdf_sha256": source_pdf_sha256,
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
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))

    extraction_id = str(inserted.inserted_id)
    background_tasks.add_task(process_extraction, extraction_id, file_path, filename)
    return {
        "extraction_id": extraction_id,
        "status": "queued",
        "filename": filename,
        "source_pdf_sha256": source_pdf_sha256,
        "message": "Extraction started",
    }


def _clear_template_storage(extraction_id: str) -> None:
    storage_dir = template_storage_dir(extraction_id)
    if storage_dir.is_dir():
        shutil.rmtree(storage_dir, ignore_errors=True)
    storage_dir.mkdir(parents=True, exist_ok=True)


@router.delete("/{extraction_id}/template")
async def clear_extraction_template(extraction_id: str):
    """Remove bound template and generated output for this job (fixes stale template binding)."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _clear_template_storage(extraction_id)
    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {
                "$unset": {
                    "template": "",
                    "generated_xml": "",
                    "semantic_mapping": "",
                }
            },
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))
    log_processing_stage(
        "template_cleared",
        extraction_id=extraction_id,
        source_pdf_sha256=doc.get("source_pdf_sha256"),
    )
    return {"extraction_id": extraction_id, "cleared": True}


@router.post("/{extraction_id}/template/from-source", response_model=TemplateUploadResponse)
async def create_template_from_source(extraction_id: str):
    """
    Generate a fresh DocBook template from this job's Phase 1 metadata only.

    Use when no publisher template is available or a prior template was rejected (409).
    """
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")
    _require_completed_extraction(doc)

    phase1 = doc.get("phase1") or (doc.get("result") or {}).get("phase1")
    if not phase1:
        raise HTTPException(status_code=409, detail="Phase 1 metadata not available yet.")

    _clear_template_storage(extraction_id)
    xml_content = build_docbook_template_xml_from_phase1(phase1)
    storage_dir = template_storage_dir(extraction_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_from_source_metadata.xml"
    file_path = storage_dir / filename
    file_path.write_text(xml_content, encoding="utf-8")

    try:
        schema = parse_template_xml(file_path)
    except ExtractionWorkflowError as exc:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    job_id = str(doc["_id"])
    template_identity = build_template_identity(
        {"template_schema": schema, "original_filename": filename},
        str(file_path),
    ).to_dict()
    template_record = build_template_record(
        template_path=file_path,
        original_filename=filename,
        schema=schema,
        bound_extraction_id=job_id,
        bound_source_pdf_sha256=doc.get("source_pdf_sha256"),
        template_content_sha256=sha256_file(file_path),
        template_identity=template_identity,
    )
    template_record["generated_from_source"] = True

    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {
                "$set": {"template": template_record},
                "$unset": {"generated_xml": "", "semantic_mapping": ""},
            },
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))

    log_processing_stage(
        "template_from_source",
        extraction_id=job_id,
        source_pdf_sha256=doc.get("source_pdf_sha256"),
        template_id=template_record["template_id"],
        identity_result=template_identity.get("title") or "-",
    )

    return TemplateUploadResponse(
        document_id=job_id,
        template_id=template_record["template_id"],
        original_filename=filename,
        created_at=template_record["created_at"],
        template_schema=schema,
    )


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
    result = dict(doc.get("result") or {})
    # Large extractions store phase1 at document root (result.phase1 may be omitted for BSON size).
    phase1 = doc.get("phase1") or result.get("phase1")
    if phase1 and not result.get("phase1"):
        result["phase1"] = phase1
    return result


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

    _clear_template_storage(extraction_id)
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

    extraction_id = str(doc["_id"])
    source_identity = build_source_identity_from_extraction_doc({**doc, "_id": extraction_id})
    template_identity = build_template_identity(
        {"template_schema": schema, "original_filename": filename},
        str(file_path),
    ).to_dict()
    content_sha = sha256_file(file_path)

    resolved_format = resolve_output_format(
        "auto",
        schema,
        template_path=file_path,
    )
    verify_pre_generation_identity(
        extraction_id=extraction_id,
        source=source_identity,
        template={
            "template_schema": schema,
            "original_filename": filename,
        },
        template_path=str(file_path),
        output_format=resolved_format,
    )

    template_record = build_template_record(
        template_path=file_path,
        original_filename=filename,
        schema=schema,
        bound_extraction_id=extraction_id,
        bound_source_pdf_sha256=doc.get("source_pdf_sha256"),
        template_content_sha256=content_sha,
        template_identity=template_identity,
    )

    log_processing_stage(
        "template_bound",
        extraction_id=extraction_id,
        source_pdf_sha256=source_identity.source_pdf_sha256,
        template_id=template_record["template_id"],
        identity_result=template_identity.get("title") or "-",
    )

    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {
                "$set": {"template": template_record},
                "$unset": {"generated_xml": "", "semantic_mapping": ""},
            },
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))

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
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))

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
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))

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
    try:
        return await _generate_extraction_xml_impl(extraction_id, body)
    except HTTPException:
        raise
    except IdentityMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("generate-xml unhandled failure for %s", extraction_id)
        raise HTTPException(
            status_code=500,
            detail=f"XML generation failed: {exc}",
        ) from exc


async def _generate_extraction_xml_impl(extraction_id: str, body: GenerateXmlRequest):
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

    bound_job = template.get("bound_extraction_id")
    if bound_job and str(bound_job) != extraction_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Template is bound to a different extraction job ({bound_job}). "
                "Upload the template again for this PDF."
            ),
        )
    bound_sha = template.get("bound_source_pdf_sha256")
    doc_sha = doc.get("source_pdf_sha256")
    if bound_sha and doc_sha and bound_sha != doc_sha:
        raise HTTPException(
            status_code=409,
            detail="Template was uploaded for a different revision of this PDF. Re-upload the template.",
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
    phase1_doc = doc.get("phase1") or (doc.get("result") or {}).get("phase1")
    filtered_ir = merge_phase1_references_into_ir(filtered_ir, phase1_doc)
    structure = (doc.get("result") or {}).get("structure") or {}
    processed_blocks = structure.get("blocks")
    try:
        mapping_resolution = resolve_semantic_mapping_for_generate_xml(
            extraction_id=extraction_id,
            resolved_scope=resolved_scope,
            filtered_ir=filtered_ir,
            filtered_template_schema=scope_result["filtered_template_schema"],
            use_llm=body.use_llm,
            llm_fallback=body.llm_fallback,
            processed_blocks=processed_blocks,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SemanticMappingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    warnings: list[str] = list(mapping_resolution.warnings)
    mapping_source = mapping_resolution.mapping_source
    prompt_version = mapping_resolution.prompt_version
    unmapped_count = mapping_resolution.unmapped_count
    if mapping_resolution.semantic_record is not None:
        try:
            extractions_col().update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "scope": resolved_scope,
                        "semantic_mapping": mapping_resolution.semantic_record,
                    }
                },
            )
        except PyMongoError as exc:
            raise HTTPException(status_code=503, detail=mongo_user_error(exc)) from exc

    mapping_body = finalize_mapping_for_xml(mapping_resolution.mapping_body, filtered_ir)

    try:
        resolved_output_format = resolve_output_format(
            body.output_format,
            template_schema,
            template_path=template_path,
        )
    except OutputFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if resolved_output_format == OUTPUT_IEEE_JATS:
        try:
            assert_jats_article_template_root(template_path)
            assert_jats_transform_payload_under_limit(template_path, mapping_body)
        except JatsArticleRequiredError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except JatsTransformTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    source_identity = build_source_identity_from_extraction_doc({**doc, "_id": extraction_id})
    output_filename = safe_output_xml_filename(
        extraction_id=extraction_id,
        original_pdf_filename=doc.get("original_filename"),
    )
    log_processing_stage(
        "generate_xml_context",
        extraction_id=extraction_id,
        source_pdf_sha256=source_identity.source_pdf_sha256,
        template_id=template.get("template_id"),
        scope=resolved_scope,
        output_format=resolved_output_format,
        output_storage_key=output_filename,
    )
    verify_pre_generation_identity(
        extraction_id=extraction_id,
        source=source_identity,
        template=template,
        template_path=template_path,
        output_format=resolved_output_format,
    )

    try:
        xml_content, resolved_output_format, docbook_result = generate_output_xml(
            template_path,
            template_schema,
            mapping_body,
            output_format=body.output_format,
            source=source_identity,
            phase1=phase1_doc,
            ir=filtered_ir,
        )
    except OutputFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except XmlGenerationError as exc:
        message = str(exc)
        if is_jats_article_required_message(message):
            raise HTTPException(status_code=422, detail=message) from exc
        if "too large" in message.lower():
            raise HTTPException(status_code=413, detail=message) from exc
        logger.exception("generate-xml JATS/DocBook transform failed for %s", extraction_id)
        raise HTTPException(status_code=500, detail=message) from exc
    except MemoryError as exc:
        logger.exception("generate-xml MemoryError for %s", extraction_id)
        raise HTTPException(
            status_code=413,
            detail="Document too large for JATS transform. Chunk by <chapter> before retrying.",
        ) from exc

    expected_root = "book" if resolved_output_format == OUTPUT_DOCBOOK_5 else "article"
    try:
        verify_post_generation_identity(
            extraction_id=extraction_id,
            source=source_identity,
            xml_content=xml_content,
            output_format=resolved_output_format,
            expected_root=expected_root,
        )
    except IdentityMismatchError:
        raise

    book_manifest: dict | None = None
    response_xml = xml_content

    if resolved_output_format == OUTPUT_DOCBOOK_5:
        if docbook_result:
            if docbook_result.metadata.warnings:
                warnings.extend(docbook_result.metadata.warnings)
            if docbook_result.body.warnings:
                warnings.extend(docbook_result.body.warnings)
            if not docbook_result.body.applied:
                warnings.append(
                    "DocBook chapter bodies were not rebuilt from the PDF "
                    "(empty IR body or merge skipped)."
                )
        try:
            write_result = write_book_chunks(extraction_id, xml_content)
        except DocBookChunkingError as exc:
            logger.exception("DocBook chapter split failed for %s", extraction_id)
            detail = str(exc)
            status = 413 if "exceeds" in detail.lower() or "too large" in detail.lower() else 422
            raise HTTPException(status_code=status, detail=detail) from exc
        except Exception as exc:
            logger.exception("DocBook chapter storage failed for %s", extraction_id)
            if "too large" in str(exc).lower():
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            raise HTTPException(
                status_code=500,
                detail=f"DocBook chapter storage failed: {exc}",
            ) from exc
        if not write_result.all_ok:
            failed = [w.document_id for w in write_result.writes if not w.ok]
            raise HTTPException(
                status_code=503,
                detail=f"DocBook chapter writes failed for: {', '.join(failed[:8])}",
            )
        book_manifest = write_result.manifest
        full_book_path = persist_full_book_xml_file(extraction_id, xml_content)
        generated_record = generated_xml_record_for_chunked_book(
            scope=resolved_scope,
            mapping_source=mapping_source,
            prompt_version=prompt_version,
            warnings=warnings,
            manifest=book_manifest,
            write_result=write_result,
        )
        generated_record["full_book_xml_path"] = full_book_path
        response_xml = xml_content
    else:
        generated_record = {
            "scope": resolved_scope,
            "mapping_source": mapping_source,
            "prompt_version": prompt_version,
            "output_format": resolved_output_format,
            "xml_content": xml_content,
            "warnings": warnings,
            "generated_at": utcnow(),
        }

    generated_record["extraction_id"] = extraction_id
    generated_record["source_pdf_sha256"] = source_identity.source_pdf_sha256
    generated_record["output_filename"] = output_filename
    generated_record["identity_verified"] = True

    try:
        extractions_col().update_one(
            {"_id": doc["_id"]},
            {"$set": {"scope": resolved_scope, "generated_xml": generated_record}},
        )
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_user_error(exc))

    return GenerateXmlResponse(
        document_id=extraction_id,
        scope=resolved_scope,
        mapping_source=mapping_source,
        prompt_version=prompt_version,
        output_format=resolved_output_format,
        xml_content=response_xml,
        warnings=generated_record.get("warnings") or warnings,
        unmapped_content_count=unmapped_count,
        book_manifest=book_manifest,
        storage_mode=generated_record.get("storage_mode"),
        output_filename=output_filename,
    )


@router.get("/{extraction_id}/download-xml")
async def download_extraction_xml(extraction_id: str):
    """Download the last generated JATS XML for an extraction."""
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Extraction not found")

    generated = doc.get("generated_xml") or {}
    if not generated:
        raise HTTPException(
            status_code=404,
            detail="No generated XML found. Call POST /generate-xml first.",
        )
    if not generated.get("identity_verified"):
        raise HTTPException(
            status_code=404,
            detail="No verified generated XML for this extraction. Regenerate XML.",
        )
    if generated.get("extraction_id") and generated.get("extraction_id") != extraction_id:
        raise HTTPException(
            status_code=409,
            detail="Generated XML belongs to a different extraction job.",
        )

    xml_content = generated.get("xml_content")
    if generated.get("storage_mode") == STORAGE_MODE_CHUNKED:
        manifest = generated.get("book_manifest")
        if not manifest or not generated.get("chapter_write_ok"):
            raise HTTPException(
                status_code=404,
                detail="Chunked DocBook output is incomplete. Regenerate XML.",
            )
        try:
            xml_content = reassemble_stored_book(extraction_id, manifest)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not reassemble DocBook chapters: {exc}",
            ) from exc
    elif not xml_content:
        raise HTTPException(
            status_code=404,
            detail="No generated XML found. Call POST /generate-xml first.",
        )

    filename = generated.get("output_filename") or safe_output_xml_filename(
        extraction_id=extraction_id,
        original_pdf_filename=doc.get("original_filename"),
    )
    from fastapi.responses import Response

    xml_bytes = xml_content.lstrip("\ufeff").encode("utf-8")
    return Response(
        content=xml_bytes,
        media_type="application/xml; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
