"""Background Stage 1 extraction. Isolated from IEEE XML conversion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from pathlib import Path

from app.config import settings
from app.database import extractions_col
from app.pipeline.debug_artifacts import write_phase1_debug_bundle
from app.pipeline.phase1.extract import extract_pdf_document
from app.services.text_extractor import PdfValidationError

logger = logging.getLogger(__name__)


def process_extraction(extraction_id: str, file_path: str, original_filename: str) -> None:
    col = extractions_col()
    oid = ObjectId(extraction_id)
    col.update_one(
        {"_id": oid},
        {"$set": {"status": "processing", "error_message": None}},
    )

    try:
        debug_dir = settings.pipeline_debug_dir / extraction_id
        phase1_doc, result = extract_pdf_document(
            file_path,
            original_filename=original_filename,
            bundle_dir=debug_dir,
        )
        result_payload = result.model_dump()
        result_payload["phase1"] = phase1_doc.model_dump()

        debug_paths: dict[str, str] | None = None
        if settings.PIPELINE_WRITE_DEBUG_ARTIFACTS:
            debug_paths = write_phase1_debug_bundle(
                debug_dir,
                pdf_path=Path(file_path),
                phase1=phase1_doc,
                full_extraction=result,
            )

        col.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "completed",
                    "result": result_payload,
                    "phase1": phase1_doc.model_dump(),
                    "page_count": result.document.page_count,
                    "requires_ocr": result.document.requires_ocr,
                    "ocr_applied": result.document.ocr_applied,
                    "phase1_debug_paths": debug_paths,
                    "error_message": None,
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
        logger.info("Extraction %s completed", extraction_id)
    except PdfValidationError as exc:
        logger.warning("Extraction %s invalid PDF: %s", extraction_id, exc)
        _fail(oid, str(exc))
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
            }
        },
    )
