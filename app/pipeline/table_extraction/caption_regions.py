"""Caption-anchored search regions for borderless academic tables."""

from __future__ import annotations

import re

from app.pipeline.table_extraction.geometry import column_bounds_for_x
from app.pipeline.table_extraction.types import CaptionInfo, PageIngest

STRICT_TABLE_CAPTION_LINE_RE = re.compile(r"^TABLE\s+[IVX0-9]+[\.\:]", re.IGNORECASE)
FIGURE_LINE_RE = re.compile(r"^FIG(?:URE)?\.?\s+[IVX0-9]+[\.\:]", re.IGNORECASE)

CAPTION_VERTICAL_WINDOW = 100.0
EXTRACTION_ABOVE_CAPTION = 200.0
EXTRACTION_BELOW_CAPTION = 120.0


def is_strict_table_caption_line(line: str) -> bool:
    return bool(STRICT_TABLE_CAPTION_LINE_RE.match(line.strip()))


def strict_table_captions(page: PageIngest) -> list[CaptionInfo]:
    caps: list[CaptionInfo] = []
    for cap in page.captions:
        if cap.caption_type != "table":
            continue
        first = (cap.text.splitlines() or [""])[0].strip()
        if is_strict_table_caption_line(first):
            caps.append(cap)
    caps.sort(key=lambda c: c.bbox[1])
    return caps


def _same_column(a_bbox: list[float], col: tuple[float, float]) -> bool:
    cx = (a_bbox[0] + a_bbox[2]) / 2.0
    return col[0] <= cx <= col[1]


def caption_search_bbox(cap: CaptionInfo, page: PageIngest, all_caps: list[CaptionInfo]) -> list[float]:
    """Region to search for table body within the same column as the caption."""
    from app.pipeline.table_extraction.table_region import caption_bounded_region

    return caption_bounded_region(cap, page, all_caps).bbox
