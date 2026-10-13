"""Ephemeral data policy: purge old jobs from MongoDB and local disk (no Redis/backup)."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import book_documents_col, conversions_col, extractions_col, get_db

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))


@dataclass
class RetentionPurgeStats:
    extractions_deleted: int = 0
    conversions_deleted: int = 0
    book_documents_deleted: int = 0
    llm_calls_deleted: int = 0
    disk_paths_removed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extractions_deleted": self.extractions_deleted,
            "conversions_deleted": self.conversions_deleted,
            "book_documents_deleted": self.book_documents_deleted,
            "llm_calls_deleted": self.llm_calls_deleted,
            "disk_paths_removed": self.disk_paths_removed,
            "errors": self.errors[:32],
        }


def _cutoff_utc(retention_days: int) -> datetime:
    days = max(1, int(retention_days))
    return datetime.now(timezone.utc) - timedelta(days=days)


def _rm_path(path: Path, stats: RetentionPurgeStats) -> None:
    if not path.exists():
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        else:
            path.unlink(missing_ok=True)
        stats.disk_paths_removed += 1
    except OSError as exc:
        stats.errors.append(f"Could not remove {path}: {exc}")


def _purge_extraction_disk(extraction_id: str, doc: dict[str, Any], stats: RetentionPurgeStats) -> None:
    file_path = doc.get("file_path")
    if file_path:
        _rm_path(Path(file_path), stats)

    roots = [
        UPLOAD_DIR / "extractions" / extraction_id,
        settings.outputs_dir / "extraction_artifacts" / extraction_id,
        settings.outputs_dir / "book_exports" / extraction_id,
        settings.pipeline_debug_dir / extraction_id,
    ]
    for root in roots:
        _rm_path(root, stats)

    template = doc.get("template") or {}
    template_path = template.get("file_path")
    if template_path:
        _rm_path(Path(template_path).parent, stats)


def purge_expired_data(retention_days: int | None = None) -> RetentionPurgeStats:
    """
    Delete extraction/conversion records older than ``retention_days`` and wipe their files.

    Intended for environments with no long-term backup (e.g. purge every ~2 days).
    """
    stats = RetentionPurgeStats()
    days = retention_days if retention_days is not None else settings.DATA_RETENTION_DAYS
    cutoff = _cutoff_utc(days)

    ext_col = extractions_col()
    for doc in ext_col.find({"created_at": {"$lt": cutoff}}):
        extraction_id = str(doc["_id"])
        try:
            _purge_extraction_disk(extraction_id, doc, stats)
            book_del = book_documents_col().delete_many({"extraction_id": extraction_id})
            stats.book_documents_deleted += int(book_del.deleted_count)
            llm_del = get_db()["llm_calls"].delete_many({"document_id": extraction_id})
            stats.llm_calls_deleted += int(llm_del.deleted_count)
            ext_col.delete_one({"_id": doc["_id"]})
            stats.extractions_deleted += 1
        except Exception as exc:
            stats.errors.append(f"extraction {extraction_id}: {exc}")

    conv_col = conversions_col()
    for doc in conv_col.find({"created_at": {"$lt": cutoff}}):
        try:
            file_path = doc.get("file_path")
            if file_path:
                _rm_path(Path(file_path), stats)
            conv_col.delete_one({"_id": doc["_id"]})
            stats.conversions_deleted += 1
        except Exception as exc:
            stats.errors.append(f"conversion {doc.get('_id')}: {exc}")

    logger.info(
        "Data retention purge (>%s days): %s",
        days,
        stats.to_dict(),
    )
    return stats


def run_retention_if_enabled() -> RetentionPurgeStats | None:
    if not settings.DATA_RETENTION_ENABLED:
        return None
    return purge_expired_data()
