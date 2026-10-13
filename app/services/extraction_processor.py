"""Background Stage 1 extraction. Isolated from IEEE XML conversion."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import settings
from app.database import extractions_col
from app.pipeline.debug_artifacts import write_phase1_debug_bundle
from app.pipeline.phase1.build_document import build_extracted_document
from app.pipeline.phase1.pdf_kind import classify_pdf_document_kind, quality_warnings
from app.pipeline.phase1.extraction_build_options import ExtractionBuildOptions
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.extraction_mongo_payload import (
    ExtractionMongoPayloadError,
    compact_extraction_result_for_mongo,
    plan_extraction_mongo_update,
)
from app.services.source_identity import build_source_identity_from_extraction_doc
from app.services.text_extractor import PdfValidationError, extract_text_layout

logger = logging.getLogger(__name__)


def _set_progress(
    col: Collection,
    oid: ObjectId,
    extraction_id: str,
    *,
    step: str,
    progress: int,
    status: str | None = None,
) -> None:
    payload: dict = {"current_step": step, "progress": max(0, min(100, progress))}
    if status:
        payload["status"] = status
    col.update_one({"_id": oid}, {"$set": payload})
    logger.info("Extraction %s: %s (%s%%)", extraction_id, step, progress)


def process_extraction(extraction_id: str, file_path: str, original_filename: str) -> None:
    col = extractions_col()
    oid = ObjectId(extraction_id)
    doc_meta = col.find_one({"_id": oid}) or {}
    skip_tables_figures = bool(doc_meta.get("skip_tables_figures"))

    logger.info(
        "Extraction %s background task started (skip_tables_figures=%s)",
        extraction_id,
        skip_tables_figures,
    )

    _set_progress(
        col,
        oid,
        extraction_id,
        step="Step 1/5: PDF uploaded",
        progress=10,
        status="processing",
    )

    try:
        _set_progress(
            col,
            oid,
            extraction_id,
            step="Step 2/5: Extracting text and layout",
            progress=25,
        )
        raw = extract_text_layout(file_path, original_filename=original_filename)
        pdf_kind = classify_pdf_document_kind(raw)
        pdf_classification = {
            "document_kind": pdf_kind,
            "warnings": quality_warnings(raw, pdf_kind),
        }

        _set_progress(
            col,
            oid,
            extraction_id,
            step="Step 3/5: Parsing document structure",
            progress=50,
        )
        full = build_full_extraction_result(raw, include_tagged_output=False)

        step4_start = time.monotonic()
        step4_deadline = step4_start + settings.EXTRACTION_STEP4_MAX_SECONDS
        page_total = raw.document.page_count

        def on_page_progress(current: int, total: int, detail: str) -> None:
            sub_pct = int(18 * current / max(total, 1))
            _set_progress(
                col,
                oid,
                extraction_id,
                step=f"Step 4/5: {detail}",
                progress=70 + sub_pct,
            )
            if current % 10 == 0 or current == total:
                logger.info(
                    "Extraction %s Step 4/5: %s (%s/%s pages)",
                    extraction_id,
                    detail,
                    current,
                    total,
                )

        build_options = ExtractionBuildOptions(
            skip_tables_figures=skip_tables_figures,
            fast_tables_figures=page_total >= settings.EXTRACTION_LARGE_PDF_PAGE_THRESHOLD,
            table_page_timeout_sec=settings.EXTRACTION_TABLE_PAGE_TIMEOUT_SEC,
            page_progress=on_page_progress,
            step4_deadline=step4_deadline,
        )

        _set_progress(
            col,
            oid,
            extraction_id,
            step=f"Step 4/5: Tables and figures (0/{page_total} pages)",
            progress=70,
        )
        debug_dir = settings.pipeline_debug_dir / extraction_id
        phase1_doc = build_extracted_document(
            raw,
            structure=full.structure,
            pdf_path=Path(file_path),
            bundle_dir=debug_dir,
            options=build_options,
        )

        if build_options.partial_step4:
            logger.warning(
                "Extraction %s: Step 4 timeout, partial results saved",
                extraction_id,
            )

        _set_progress(
            col,
            oid,
            extraction_id,
            step="Step 5/5: Saving extraction results",
            progress=90,
        )
        result_payload = full.model_dump()
        phase1_dump = phase1_doc.model_dump()
        result_payload["phase1"] = phase1_dump

        debug_paths: dict[str, str] | None = None
        if settings.PIPELINE_WRITE_DEBUG_ARTIFACTS:
            debug_paths = write_phase1_debug_bundle(
                debug_dir,
                pdf_path=Path(file_path),
                phase1=phase1_doc,
                full_extraction=full,
            )

        mongo_result, mongo_phase1, mongo_flags = compact_extraction_result_for_mongo(
            result_payload,
            phase1_dump,
            extraction_id=extraction_id,
        )

        update_fields: dict = {
            "status": "completed",
            "result": mongo_result,
            "phase1": mongo_phase1,
            "page_count": full.document.page_count,
            "requires_ocr": full.document.requires_ocr,
            "ocr_applied": full.document.ocr_applied,
            "phase1_debug_paths": debug_paths,
            "error_message": None,
            "completed_at": datetime.now(timezone.utc),
            "current_step": "Extraction complete",
            "progress": 100,
            "step4_partial": build_options.partial_step4,
            "pdf_classification": pdf_classification,
            "workflow_stage": "extraction_complete",
        }
        storage_flags = dict(mongo_flags or {})
        if storage_flags:
            update_fields["phase1_storage_flags"] = storage_flags

        preview_doc = {
            "_id": str(oid),
            "original_filename": original_filename,
            "source_pdf_sha256": doc_meta.get("source_pdf_sha256"),
            "phase1": mongo_phase1,
            "page_count": full.document.page_count,
        }
        update_fields["source_identity"] = build_source_identity_from_extraction_doc(
            preview_doc
        ).to_dict()

        try:
            set_fields, unset_fields, plan_flags = plan_extraction_mongo_update(
                doc_meta,
                update_fields,
                extraction_id=extraction_id,
            )
            storage_flags.update(plan_flags)
            if storage_flags:
                set_fields["phase1_storage_flags"] = storage_flags
            update_doc: dict = {"$set": set_fields}
            if unset_fields:
                update_doc["$unset"] = unset_fields
            col.update_one({"_id": oid}, update_doc)
        except ExtractionMongoPayloadError as exc:
            _fail(oid, str(exc))
            return
        logger.info("Extraction %s completed (%s pages)", extraction_id, full.document.page_count)
    except PdfValidationError as exc:
        logger.warning("Extraction %s invalid PDF: %s", extraction_id, exc)
        _fail(oid, str(exc))
    except PyMongoError as exc:
        logger.exception("Extraction %s MongoDB error", extraction_id)
        _fail(oid, f"Could not save extraction results: {exc}")
    except Exception as exc:
        logger.exception("Extraction %s failed", extraction_id)
        _fail(oid, str(exc))


def _fail(oid: ObjectId, message: str) -> None:
    extractions_col().update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "failed",
                "error_message": message,
                "completed_at": datetime.now(timezone.utc),
                "current_step": "Extraction failed",
                "progress": 0,
            }
        },
    )
