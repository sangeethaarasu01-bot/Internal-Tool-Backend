"""Step 3: Strict TABLE caption matching (no body-text fragments)."""

from __future__ import annotations

import re

from app.pipeline.table_extraction.caption_regions import (
    CAPTION_VERTICAL_WINDOW,
    is_strict_table_caption_line,
)
from app.pipeline.table_extraction.geometry import horizontal_overlap_ratio
from app.pipeline.table_extraction.types import CaptionInfo, PageIngest

INLINE_TABLE_REF_RE = re.compile(
    r"(?:\bin\s+Table\b|\bas\s+(?:shown|summarized|listed)\s+in\s+Table\b)",
    re.IGNORECASE,
)


def _vertical_distance(cap: CaptionInfo, table_bbox: list[float]) -> float:
    """Smallest vertical gap between caption and table boxes (IEEE caption above or below)."""
    cap_top, cap_bottom = cap.bbox[1], cap.bbox[3]
    tbl_top, tbl_bottom = table_bbox[1], table_bbox[3]
    if cap_bottom <= tbl_top + 4:
        return max(0.0, tbl_top - cap_bottom)
    if tbl_bottom <= cap_top + 4:
        return max(0.0, cap_top - tbl_bottom)
    cy = (cap_top + cap_bottom) / 2.0
    ty = (tbl_top + tbl_bottom) / 2.0
    return abs(cy - ty)


def _caption_line_text(cap: CaptionInfo) -> str:
    lines = [ln.strip() for ln in cap.text.splitlines() if ln.strip()]
    if not lines:
        return ""
    if is_strict_table_caption_line(lines[0]):
        return "\n".join(lines)
    return ""


def match_table_caption(
    page: PageIngest,
    table_bbox: list[float],
    *,
    bound_caption: str | None = None,
) -> tuple[str | None, float, bool]:
    if bound_caption and is_strict_table_caption_line(bound_caption.splitlines()[0]):
        return bound_caption, 0.95, True

    candidates: list[tuple[float, float, CaptionInfo]] = []
    for cap in page.captions:
        if cap.caption_type != "table":
            continue
        line_text = _caption_line_text(cap)
        if not line_text:
            continue
        if INLINE_TABLE_REF_RE.search(line_text):
            continue
        dist = _vertical_distance(cap, table_bbox)
        if dist > CAPTION_VERTICAL_WINDOW:
            continue
        h_overlap = horizontal_overlap_ratio(cap.bbox, table_bbox)
        if h_overlap < 0.05 and dist > 40:
            continue
        candidates.append((dist, h_overlap, cap))

    if not candidates:
        return None, 0.0, False

    candidates.sort(key=lambda t: (t[0], -t[1]))
    cap = candidates[0][2]
    dist, h_overlap, _ = candidates[0]
    conf = min(1.0, 0.5 * (1.0 - dist / CAPTION_VERTICAL_WINDOW) + 0.5 * min(1.0, h_overlap + 0.2))
    return _caption_line_text(cap), round(conf, 3), True
