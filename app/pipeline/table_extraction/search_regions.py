"""Dynamic search regions for per-engine table detection."""

from __future__ import annotations

from app.pipeline.table_extraction.caption_regions import caption_search_bbox, strict_table_captions
from app.pipeline.table_extraction.geometry import bbox_area, column_bounds_for_x, intersection_area
from app.pipeline.table_extraction.types import PageIngest

_MARGIN = 36.0
_MIN_REGION_AREA = 8000.0


def _merge_regions(regions: list[list[float]]) -> list[list[float]]:
    if not regions:
        return []
    merged: list[list[float]] = []
    for reg in sorted(regions, key=lambda r: (r[1], r[0])):
        if bbox_area(reg) < _MIN_REGION_AREA:
            continue
        placed = False
        for i, existing in enumerate(merged):
            if intersection_area(reg, existing) / max(bbox_area(reg), 1.0) > 0.65:
                x0 = min(reg[0], existing[0])
                y0 = min(reg[1], existing[1])
                x1 = max(reg[2], existing[2])
                y1 = max(reg[3], existing[3])
                merged[i] = [x0, y0, x1, y1]
                placed = True
                break
        if not placed:
            merged.append(list(reg))
    return merged


def _column_page_regions(page: PageIngest) -> list[list[float]]:
    w, h = page.page_width, page.page_height
    mid = w / 2.0
    gutter = 14.0
    regions = [
        [_MARGIN, _MARGIN, mid - gutter, h - _MARGIN],
        [mid + gutter, _MARGIN, w - _MARGIN, h - _MARGIN],
    ]
    return [r for r in regions if bbox_area(r) >= _MIN_REGION_AREA]


def _block_gap_regions(page: PageIngest) -> list[list[float]]:
    """Large vertical gaps between text blocks suggest table-friendly whitespace."""
    blocks = sorted(page.blocks, key=lambda b: b.bbox[1])
    regions: list[list[float]] = []
    for i in range(len(blocks) - 1):
        upper = blocks[i]
        lower = blocks[i + 1]
        gap = lower.bbox[1] - upper.bbox[3]
        if gap < 28 or gap > 220:
            continue
        x0 = min(upper.bbox[0], lower.bbox[0]) - 8
        x1 = max(upper.bbox[2], lower.bbox[2]) + 8
        y0 = upper.bbox[3] + 2
        y1 = lower.bbox[1] - 2
        col = column_bounds_for_x((x0 + x1) / 2, page.page_width)
        regions.append([max(col[0], x0), y0, min(col[1], x1), y1])
    return regions


def build_search_regions(page: PageIngest) -> list[list[float]]:
    caps = strict_table_captions(page)
    if caps:
        regions = [caption_search_bbox(cap, page, caps) for cap in caps]
        return _merge_regions(regions)

    regions: list[list[float]] = []
    regions.extend(_column_page_regions(page))
    regions.extend(_block_gap_regions(page))
    return _merge_regions(regions)
