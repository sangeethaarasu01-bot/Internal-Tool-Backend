"""Column position detection from block bounding boxes."""

from __future__ import annotations

from app.models.document_structure import ColumnPosition
from app.models.extraction import TextBlock

GUTTER = 18.0


def classify_column(bbox: list[float], page_width: float) -> ColumnPosition:
    x0, _y0, x1, _y1 = bbox
    mid = page_width / 2.0
    if x0 < mid - GUTTER and x1 > mid + GUTTER:
        return "FULL_WIDTH"
    if x0 >= mid - GUTTER:
        return "RIGHT"
    return "LEFT"


def classify_block_column(block: TextBlock, page_width: float) -> ColumnPosition:
    return classify_column(block.bbox, page_width)
