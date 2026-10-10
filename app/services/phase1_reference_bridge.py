"""Bridge Phase 1 bibliography records into partitioned semantic IR."""

from __future__ import annotations

import copy
import re
from typing import Any

from app.models.document_structure import ProcessedBlock
from app.utils.reference_assembler import assemble_references_from_blocks

_REFERENCE_START_RE = re.compile(r"^\[1\]\b")
_REFERENCE_LABEL_RE = re.compile(r"^\[\d+\]")
_RUNNING_HEADER_RE = re.compile(r"\bet al\.:\s*.+", re.IGNORECASE)


def _is_interleaved_running_header(text: str) -> bool:
    """Drop IEEE running headers that appear between bibliography blocks."""
    stripped = text.strip()
    if _REFERENCE_LABEL_RE.match(stripped):
        return False
    return bool(_RUNNING_HEADER_RE.search(stripped))


def _phase1_items_to_blocks(phase1: dict[str, Any]) -> list[ProcessedBlock]:
    items = phase1.get("references") or []
    start = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if text and _REFERENCE_START_RE.match(text.replace("\n", " ")):
            start = index
            break

    blocks: list[ProcessedBlock] = []
    for order, item in enumerate(items[start:], start=0):
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text or _is_interleaved_running_header(text):
            continue
        block_ids = list(item.get("source_block_ids") or [])
        blocks.append(
            ProcessedBlock(
                block_id=block_ids[0] if block_ids else f"phase1_ref_{order}",
                page_number=int(item.get("page_number") or 1),
                reading_order_index=order,
                column="FULL_WIDTH",
                classification="REFERENCE_TEXT",
                bbox=[0.0, 0.0, 0.0, 0.0],
                text=text,
                block_type="paragraph",
            )
        )
    return blocks


def phase1_references_to_ir_nodes(phase1: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert ``phase1['references']`` to semantic IR reference nodes (merged entries)."""
    blocks = _phase1_items_to_blocks(phase1)
    if not blocks:
        return []
    ir_nodes = assemble_references_from_blocks(blocks, validate=False)
    return [node.model_dump(mode="json") for node in ir_nodes]


def _should_replace_ir_references(existing: list[Any], phase1_nodes: list[dict[str, Any]]) -> bool:
    if not phase1_nodes:
        return False
    if not existing:
        return True
    return len(phase1_nodes) > len(existing)


def merge_phase1_references_into_ir(
    ir: dict[str, Any],
    phase1: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    When layout semantic IR has no (or sparse) ``back.references``, use Phase 1 bibliography.

    Phase 1 extraction often captures the reference list even when the legacy
    semantic builder leaves ``back.references`` empty.
    """
    if not phase1:
        return ir
    back = ir.get("back") or {}
    existing = back.get("references") or []
    nodes = phase1_references_to_ir_nodes(phase1)
    if not _should_replace_ir_references(existing, nodes):
        return ir
    merged = copy.deepcopy(ir)
    merged_back = dict(merged.get("back") or {})
    merged_back.setdefault("reference_list", None)
    merged_back.setdefault("other", [])
    merged_back["references"] = nodes
    merged["back"] = merged_back
    return merged
