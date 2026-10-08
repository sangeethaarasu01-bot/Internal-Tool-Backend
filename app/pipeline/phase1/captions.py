"""Caption detection for Phase 1 (layout + pattern heuristics, no LLM)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.document_structure import ProcessedBlock
from app.models.extracted_document import ExtractedCaption
from app.services.layout.semantic_patterns import (
    FIGURE_CAPTION_RE,
    TABLE_CAPTION_RE,
    first_line,
    normalize_text,
)


@dataclass(frozen=True)
class CaptionCandidate:
    page_number: int
    text: str
    bbox: list[float]
    block_ids: list[str]
    caption_type: str


def _caption_type(text: str) -> str:
    line = first_line(normalize_text(text))
    if FIGURE_CAPTION_RE.match(line):
        return "figure"
    if TABLE_CAPTION_RE.match(line):
        return "table"
    if text.strip().upper().startswith("FIGURE ") or text.strip().upper().startswith("FIG. "):
        return "figure"
    return "unknown"


def collect_caption_candidates(processed: list[ProcessedBlock]) -> list[CaptionCandidate]:
    candidates: list[CaptionCandidate] = []
    for block in processed:
        if block.exclude_from_content:
            continue
        text = (block.text or "").strip()
        if not text:
            continue
        ctype = _caption_type(text)
        if block.classification in {"CAPTION", "FIGURE"} and ctype == "unknown":
            ctype = "figure"
        if ctype == "unknown" and block.classification != "CAPTION":
            continue
        if ctype == "unknown" and block.classification == "CAPTION":
            ctype = "figure"
        candidates.append(
            CaptionCandidate(
                page_number=block.page_number,
                text=text,
                bbox=list(block.bbox),
                block_ids=[block.block_id],
                caption_type=ctype,
            )
        )
    return candidates


def build_caption_records(candidates: list[CaptionCandidate]) -> list[ExtractedCaption]:
    records: list[ExtractedCaption] = []
    for index, cand in enumerate(candidates, start=1):
        records.append(
            ExtractedCaption(
                caption_id=f"cap_{index}",
                page_number=cand.page_number,
                caption_type=cand.caption_type,
                text=cand.text,
                bbox=cand.bbox,
                source_block_ids=cand.block_ids,
            )
        )
    return records


def nearest_caption(
    candidates: list[CaptionCandidate],
    *,
    page_number: int,
    bbox: list[float] | None,
    caption_type: str,
    max_vertical_gap: float = 120.0,
) -> CaptionCandidate | None:
    if not bbox or len(bbox) < 4:
        return None
    target_y = bbox[3]
    best: CaptionCandidate | None = None
    best_gap = max_vertical_gap
    for cand in candidates:
        if cand.page_number != page_number:
            continue
        if caption_type != "any" and cand.caption_type not in {caption_type, "unknown"}:
            continue
        if len(cand.bbox) < 4:
            continue
        gap = abs(cand.bbox[1] - target_y)
        if cand.bbox[1] >= bbox[1] - 5:
            gap = cand.bbox[1] - bbox[3]
        if 0 <= gap < best_gap:
            best_gap = gap
            best = cand
    return best
