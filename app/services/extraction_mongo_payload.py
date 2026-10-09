"""Keep extraction MongoDB updates under the BSON document size limit."""

from __future__ import annotations

import copy
from typing import Any

from app.services.mongo_bson_limits import MONGODB_MAX_BSON_DOCUMENT_BYTES, bson_encoded_size

# Reserve space for field names and sibling extraction metadata on the same document.
_BSON_HEADROOM = 96 * 1024


def _strip_phase1_bulk_text(phase1: dict[str, Any]) -> bool:
    changed = False
    if phase1.pop("raw_text", None) is not None:
        changed = True
    if phase1.pop("normalized_text", None) is not None:
        changed = True
    for page in phase1.get("pages") or []:
        if isinstance(page, dict) and page.pop("raw_page_text", None) is not None:
            changed = True
    return changed


def compact_extraction_result_for_mongo(
    result_payload: dict[str, Any],
    phase1: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Return ``(result_payload, phase1, flags)`` safe to embed in an extraction document.

    Large book extractions externalize full ``raw_text`` to debug artifacts on disk;
    the API still serves structured phase1 without duplicating megabytes in MongoDB.
    """
    flags: dict[str, Any] = {}
    result_copy = copy.deepcopy(result_payload)
    phase1_copy = copy.deepcopy(phase1)

    probe = {
        "result": result_copy,
        "phase1": phase1_copy,
    }
    limit = MONGODB_MAX_BSON_DOCUMENT_BYTES - _BSON_HEADROOM
    if bson_encoded_size(probe) <= limit:
        return result_copy, phase1_copy, flags

    if _strip_phase1_bulk_text(phase1_copy):
        flags["phase1_text_externalized"] = True
    probe["phase1"] = phase1_copy
    if bson_encoded_size(probe) <= limit:
        return result_copy, phase1_copy, flags

    # Drop duplicate phase1 inside result to avoid storing the same tree twice.
    if "phase1" in result_copy:
        result_copy.pop("phase1", None)
        flags["result_phase1_omitted"] = True
    if bson_encoded_size({"result": result_copy, "phase1": phase1_copy}) <= limit:
        return result_copy, phase1_copy, flags

    flags["phase1_storage_warning"] = (
        "Extraction metadata still exceeds MongoDB size after compaction; "
        "see phase1_debug_paths on disk."
    )
    return result_copy, phase1_copy, flags
