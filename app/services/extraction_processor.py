"""Background Stage 1 extraction. Isolated from IEEE XML conversion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import settings
from app.database import extractions_col
from app.pipeline.debug_artifacts import write_phase1_debug_bundle
from app.pipeline.phase1.build_document import build_extracted_document
from app.services.layout.document_pipeline import build_full_extraction_result
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
    logger.info("Extraction %s background task started", extraction_id)

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

        _set_progress(
            col,
            oid,
            extraction_id,
            step="Step 3/5: Parsing document structure",
            progress=50,
        )
        full = build_full_extraction_result(raw, include_tagged_output=False)

        _set_progress(
            col,
            oid,
            extraction_id,
            step="Step 4/5: Tables and figures",
            progress=70,
        )
        debug_dir = settings.pipeline_debug_dir / extraction_id
        phase1_doc = build_extracted_document(
            raw,
            structure=full.structure,
            pdf_path=Path(file_path),
            bundle_dir=debug_dir,
        )

        _set_progress(
            col,
            oid,
            extraction_id,
            step="Step 5/5: Saving extraction results",
            progress=90,
        )
        result_payload = full.model_dump()
        result_payload["phase1"] = phase1_doc.model_dump()

        debug_paths: dict[str, str] | None = None
        if settings.PIPELINE_WRITE_DEBUG_ARTIFACTS:
            debug_paths = write_phase1_debug_bundle(
                debug_dir,
                pdf_path=Path(file_path),
                phase1=phase1_doc,
                full_extraction=full,
            )

        col.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "completed",
                    "result": result_payload,
                    "phase1": phase1_doc.model_dump(),
                    "page_count": full.document.page_count,
                    "requires_ocr": full.document.requires_ocr,
                    "ocr_applied": full.document.ocr_applied,
                    "phase1_debug_paths": debug_paths,
                    "error_message": None,
                    "completed_at": datetime.now(timezone.utc),
                    "current_step": "Extraction complete",
                    "progress": 100,
                }
            },
        )
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
