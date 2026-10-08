"""Caption-bounded table search regions (generic academic PDFs)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.pipeline.table_extraction.caption_regions import (
    EXTRACTION_ABOVE_CAPTION,
    FIGURE_LINE_RE,
    is_strict_table_caption_line,
)
from app.pipeline.table_extraction.geometry import column_bounds_for_x
from app.pipeline.table_extraction.types import CaptionInfo, PageIngest, TextBlockInfo

_GAP_BELOW_CAPTION = 5.0
_BOUNDARY_GAP = 5.0
_MIN_REGION_HEIGHT = 150.0
_PAGE_BOTTOM_MARGIN = 100.0
_MARGIN = 36.0

SECTION_HEADING_RE = re.compile(
    r"^(?:[IVXLC]+\.|[0-9]+\.)\s+[A-ZÀ-ÖØ-Þ]",
)
CITATION_IN_TEXT_RE = re.compile(r"\[\d{1,3}\]")


@dataclass
class CaptionTableRegion:
    caption_bbox: list[float]
    bbox: list[float]
    region_y_top: float
    region_y_bottom: float
    next_element_type: str
    next_element_y0: float | None
    text_blocks_in_region: list[dict[str, object]] = field(default_factory=list)


def _same_column(block_bbox: list[float], cap_bbox: list[float], page_width: float) -> bool:
    col = column_bounds_for_x((cap_bbox[0] + cap_bbox[2]) / 2.0, page_width)
    cx = (block_bbox[0] + block_bbox[2]) / 2.0
    return col[0] <= cx <= col[1]


def _classify_boundary_block(block: TextBlockInfo, cap: CaptionInfo) -> str | None:
    lines = [ln.strip() for ln in block.text.splitlines() if ln.strip()]
    if not lines:
        return None
    first = lines[0]
    if is_strict_table_caption_line(first) and block.bbox[1] > cap.bbox[3] + 2:
        return "TABLE"
    if FIGURE_LINE_RE.match(first):
        return "FIGURE"
    if SECTION_HEADING_RE.match(first):
        return "SECTION"
    if len(lines) >= 3:
        long_lines = sum(1 for ln in lines if len(ln) > 70)
        ends_sentence = any(ln.rstrip().endswith(".") and len(ln) > 60 for ln in lines)
        if long_lines >= 2 and ends_sentence and block.bbox[1] > cap.bbox[3] + 120:
            return "PARAGRAPH"
    return None


def _blocks_in_region(page: PageIngest, region: list[float]) -> list[TextBlockInfo]:
    x0, y0, x1, y1 = region
    hits: list[TextBlockInfo] = []
    for block in page.blocks:
        if block.bbox[1] >= y1 or block.bbox[3] <= y0:
            continue
        if block.bbox[0] >= x1 or block.bbox[2] <= x0:
            continue
        hits.append(block)
    hits.sort(key=lambda b: b.bbox[1])
    return hits


def _region_below_caption(
    cap: CaptionInfo,
    page: PageIngest,
    all_caps: list[CaptionInfo],
    col: tuple[float, float],
) -> tuple[list[float], str, float | None]:
    x0, y0, x1, y1 = cap.bbox
    region_top = y1 + _GAP_BELOW_CAPTION
    next_type = "END_OF_PAGE"
    next_y0: float | None = None
    for block in sorted(page.blocks, key=lambda b: b.bbox[1]):
        if block.bbox[1] <= y1 + 2:
            continue
        if not _same_column(block.bbox, cap.bbox, page.page_width):
            continue
        kind = _classify_boundary_block(block, cap)
        if kind:
            next_type = kind
            next_y0 = block.bbox[1]
            break

    if next_y0 is not None:
        region_bottom = next_y0 - _BOUNDARY_GAP
    else:
        region_bottom = page.page_height - _PAGE_BOTTOM_MARGIN

    for other in all_caps:
        if other is cap:
            continue
        if not _same_column(other.bbox, cap.bbox, page.page_width):
            continue
        if other.bbox[1] > y1 and other.bbox[1] < region_bottom + 20:
            region_bottom = min(region_bottom, other.bbox[1] - _BOUNDARY_GAP)
            next_type = "TABLE"
            next_y0 = other.bbox[1]

    if region_bottom - region_top < _MIN_REGION_HEIGHT:
        extended = region_top + _MIN_REGION_HEIGHT
        cap_on_page = [
            c
            for c in all_caps
            if c is not cap and _same_column(c.bbox, cap.bbox, page.page_width) and c.bbox[1] > y1
        ]
        cap_on_page.sort(key=lambda c: c.bbox[1])
        upper_limit = (
            cap_on_page[0].bbox[1] - _BOUNDARY_GAP
            if cap_on_page
            else page.page_height - _PAGE_BOTTOM_MARGIN
        )
        region_bottom = min(max(region_bottom, extended), upper_limit)

    region_bottom = min(region_bottom, page.page_height - _MARGIN)
    region_top = max(region_top, _MARGIN)
    return [col[0], region_top, col[1], region_bottom], next_type, next_y0


def _region_above_caption(
    cap: CaptionInfo,
    page: PageIngest,
    all_caps: list[CaptionInfo],
    col: tuple[float, float],
) -> tuple[list[float], str, float | None]:
    x0, y0, x1, y1 = cap.bbox
    region_bottom = y0 - _BOUNDARY_GAP
    next_type = "START_OF_COLUMN"
    next_y0: float | None = None

    prev_caps = [
        c
        for c in all_caps
        if c is not cap
        and _same_column(c.bbox, cap.bbox, page.page_width)
        and c.bbox[3] <= y0 + 2
    ]
    prev_caps.sort(key=lambda c: c.bbox[3], reverse=True)
    region_top = _MARGIN
    if prev_caps:
        region_top = max(region_top, prev_caps[0].bbox[3] + _GAP_BELOW_CAPTION)
        next_type = "TABLE"
        next_y0 = prev_caps[0].bbox[1]

    for block in sorted(page.blocks, key=lambda b: b.bbox[3], reverse=True):
        if block.bbox[1] >= y0 - 2:
            continue
        if block.bbox[3] <= region_top:
            continue
        if not _same_column(block.bbox, cap.bbox, page.page_width):
            continue
        kind = _classify_boundary_block(block, cap)
        if kind in {"FIGURE", "SECTION", "TABLE"}:
            region_top = max(region_top, block.bbox[3] + _BOUNDARY_GAP)
            next_type = kind
            next_y0 = block.bbox[1]
            break

    if region_bottom - region_top < _MIN_REGION_HEIGHT:
        region_top = max(_MARGIN, region_bottom - EXTRACTION_ABOVE_CAPTION)

    region_top = max(region_top, _MARGIN)
    region_bottom = min(region_bottom, page.page_height - _MARGIN)
    return [col[0], region_top, col[1], region_bottom], next_type, next_y0


def caption_bounded_region(
    cap: CaptionInfo,
    page: PageIngest,
    all_caps: list[CaptionInfo],
) -> CaptionTableRegion:
    x0, y0, x1, y1 = cap.bbox
    col = column_bounds_for_x((x0 + x1) / 2.0, page.page_width)
    # Captions near the top of the page: table body is below. Otherwise table is above.
    if y1 <= page.page_height * 0.28:
        bbox, next_type, next_y0 = _region_below_caption(cap, page, all_caps, col)
    else:
        bbox, next_type, next_y0 = _region_above_caption(cap, page, all_caps, col)

    blocks = _blocks_in_region(page, bbox)
    block_summaries = [
        {
            "bbox": b.bbox,
            "preview": (b.text.splitlines() or [""])[0][:120],
            "line_count": len([ln for ln in b.text.splitlines() if ln.strip()]),
        }
        for b in blocks
    ]

    return CaptionTableRegion(
        caption_bbox=list(cap.bbox),
        bbox=bbox,
        region_y_top=bbox[1],
        region_y_bottom=bbox[3],
        next_element_type=next_type,
        next_element_y0=next_y0,
        text_blocks_in_region=block_summaries,
    )


def caption_search_bbox(cap: CaptionInfo, page: PageIngest, all_caps: list[CaptionInfo]) -> list[float]:
    return caption_bounded_region(cap, page, all_caps).bbox
