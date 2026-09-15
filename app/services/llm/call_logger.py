"""Lightweight MongoDB logging for LLM semantic mapping calls."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.database import get_db

logger = logging.getLogger(__name__)


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def log_llm_call(
    *,
    document_id: str,
    prompt_version: str,
    provider: str,
    model: str,
    input_payload: dict[str, Any],
    output_text: str | None,
    success: bool,
    error: str | None = None,
    latency_ms: float | None = None,
) -> None:
    """Persist an LLM call record (metadata + hashes, not full PDF content)."""
    record = {
        "document_id": document_id,
        "prompt_version": prompt_version,
        "provider": provider,
        "model": model,
        "timestamp": datetime.now(timezone.utc),
        "input_hash": _hash_payload(input_payload),
        "output_hash": _hash_payload(output_text) if output_text else None,
        "success": success,
        "error": error,
        "latency_ms": latency_ms,
    }
    try:
        get_db()["llm_calls"].insert_one(record)
    except Exception:
        logger.exception("Failed to persist LLM call log for document %s", document_id)
