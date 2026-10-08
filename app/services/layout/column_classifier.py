"""Column position detection from block bounding boxes."""

from __future__ import annotations

from statistics import median

from app.models.document_structure import ColumnPosition
from app.models.extraction import PageExtraction, TextBlock

GUTTER = 18.0

SPANNING_COLUMN_ID = -1
LEFT_COLUMN_ID = 0
RIGHT_COLUMN_ID = 1


def block_column_id(bbox: list[float], page_width: float) -> int:
    """Return 0 (left), 1 (right), or -1 (spanning full width)."""
    x0, _y0, x1, _y1 = bbox
    midpoint = page_width / 2.0
    tolerance = GUTTER
    if x0 < midpoint and x1 <= midpoint + tolerance:
        return LEFT_COLUMN_ID
    if x0 >= midpoint - tolerance and x1 > midpoint:
        return RIGHT_COLUMN_ID
    return SPANNING_COLUMN_ID


def classify_column(bbox: list[float], page_width: float) -> ColumnPosition:
    column_id = block_column_id(bbox, page_width)
    if column_id == RIGHT_COLUMN_ID:
        return "RIGHT"
    if column_id == SPANNING_COLUMN_ID:
        return "FULL_WIDTH"
    return "LEFT"


def classify_block_column(block: TextBlock, page_width: float) -> ColumnPosition:
    if block.column_id is not None:
        if block.column_id == RIGHT_COLUMN_ID:
            return "RIGHT"
        if block.column_id == SPANNING_COLUMN_ID:
            return "FULL_WIDTH"
        return "LEFT"
    return classify_column(block.bbox, page_width)


def _block_column_for_detection(block: TextBlock, page_width: float) -> int:
    if block.column_id is not None:
        return block.column_id
    return block_column_id(block.bbox, page_width)


def _is_meaningful_text_block(block: TextBlock) -> bool:
    return block.type == "text" and len((block.text or "").strip()) >= 24


def detect_page_columns(blocks: list[TextBlock], page_width: float) -> int:
    """Return 1 for single-column pages, 2 when both left and right columns have text."""
    text_blocks = [block for block in blocks if block.type == "text" and (block.text or "").strip()]
    if not text_blocks:
        return 1

    meaningful_long = [block for block in text_blocks if _is_meaningful_text_block(block)]
    meaningful = meaningful_long if meaningful_long else text_blocks

    left_blocks = [
        block
        for block in meaningful
        if _block_column_for_detection(block, page_width) == LEFT_COLUMN_ID
    ]
    right_blocks = [
        block
        for block in meaningful
        if _block_column_for_detection(block, page_width) == RIGHT_COLUMN_ID
    ]
    spanning_blocks = [
        block
        for block in meaningful
        if _block_column_for_detection(block, page_width) == SPANNING_COLUMN_ID
    ]

    if meaningful_long:
        long_right = sum(
            1
            for block in meaningful_long
            if _block_column_for_detection(block, page_width) == RIGHT_COLUMN_ID
        )
        right_share = long_right / max(1, len(meaningful_long))
        if right_share < 0.25 and len(left_blocks) >= 2:
            return 1

    if spanning_blocks and meaningful_long:
        span_widths = [block.bbox[2] - block.bbox[0] for block in spanning_blocks if len(block.bbox) >= 4]
        if span_widths and max(span_widths) >= page_width * 0.55:
            long_right = sum(
                1
                for block in meaningful_long
                if _block_column_for_detection(block, page_width) == RIGHT_COLUMN_ID
            )
            right_share = long_right / max(1, len(meaningful_long))
            if right_share < 0.35:
                return 1

    if left_blocks and right_blocks:
        left_centers = [(block.bbox[0] + block.bbox[2]) / 2.0 for block in left_blocks if len(block.bbox) >= 4]
        right_centers = [(block.bbox[0] + block.bbox[2]) / 2.0 for block in right_blocks if len(block.bbox) >= 4]
        if left_centers and right_centers:
            separation = median(right_centers) - median(left_centers)
            if separation < page_width * 0.28:
                return 1
        return 2
    return 1


def annotate_page_columns(page: PageExtraction) -> PageExtraction:
    """Assign ``column_id`` on each block and ``columns`` on the page."""
    blocks: list[TextBlock] = []
    for block in page.blocks:
        column_id = block_column_id(block.bbox, page.width)
        blocks.append(
            block if block.column_id == column_id else block.model_copy(update={"column_id": column_id})
        )
    columns = detect_page_columns(blocks, page.width)
    return page.model_copy(update={"blocks": blocks, "columns": columns})
