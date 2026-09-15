"""Background Stage 1 extraction. Isolated from IEEE XML conversion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from app.database import extractions_col
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.text_extractor import PdfValidationError, extract_text_layout

logger = logging.getLogger(__name__)


def process_extraction(extraction_id: str, file_path: str, original_filename: str) -> None:
    col = extractions_col()
    oid = ObjectId(extraction_id)
    col.update_one(
        {"_id": oid},
        {"$set": {"status": "processing", "error_message": None}},
    )

    try:
        raw = extract_text_layout(file_path, original_filename=original_filename)
        result = build_full_extraction_result(raw)
        col.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "completed",
                    "result": result.model_dump(),
                    "page_count": result.document.page_count,
                    "requires_ocr": result.document.requires_ocr,
                    "ocr_applied": result.document.ocr_applied,
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
