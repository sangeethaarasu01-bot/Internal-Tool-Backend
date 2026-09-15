"""Placeholder for /api/conversions until Phase 2 wires the Hybrid AI pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from app.database import conversions_col

logger = logging.getLogger(__name__)

LEGACY_PIPELINE_DISABLED_MESSAGE = (
    "Legacy PDF→XML conversion is disabled. "
    "Use /api/extractions for Stage 1 IR extraction. "
    "Full scoped XML generation arrives in Phase 2 (llm_semantic_mapper)."
)


def reject_legacy_conversion(conversion_id: str, file_path: str) -> None:
    """Mark a conversion as failed — legacy pipeline no longer runs in production."""
    col = conversions_col()
    oid = ObjectId(conversion_id)
    logger.warning(
        "Rejected legacy conversion %s for %s — pipeline disabled",
        conversion_id,
        file_path,
    )
    col.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "failed",
                "error_message": LEGACY_PIPELINE_DISABLED_MESSAGE,
                "completed_at": datetime.now(timezone.utc),
            }
        },
    )
