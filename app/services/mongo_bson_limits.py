"""MongoDB BSON document size limits (server max 16 MiB per document)."""

from __future__ import annotations

import os
from typing import Any

import bson

# MongoDB hard limit per BSON document (bytes).
MONGODB_MAX_BSON_DOCUMENT_BYTES: int = 16 * 1024 * 1024

# Default safety margin so nested field overhead does not exceed the server limit.
_DEFAULT_PAYLOAD_CAP = 14 * 1024 * 1024


def mongodb_max_payload_bytes() -> int:
    """Maximum serialized payload size for a single stored subdocument or write."""
    try:
        from app.config import settings

        return int(settings.MONGODB_MAX_PAYLOAD_BYTES)
    except Exception:
        pass
    raw = os.getenv("MONGODB_MAX_PAYLOAD_BYTES", "").strip()
    if raw:
        try:
            return max(1024, int(raw))
        except ValueError:
            pass
    return _DEFAULT_PAYLOAD_CAP


def bson_encoded_size(value: Any) -> int:
    """Return the BSON-encoded size of a Python structure."""
    return len(bson.BSON.encode(value))


def payload_within_limit(payload_bytes: int, *, limit: int | None = None) -> bool:
    cap = limit if limit is not None else mongodb_max_payload_bytes()
    return payload_bytes <= cap
