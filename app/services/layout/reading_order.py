"""Two-column aware reading order reconstruction."""

from __future__ import annotations

from app.models.extraction import PageExtraction, TextBlock
from app.services.layout.column_classifier import (
    LEFT_COLUMN_ID,
    RIGHT_COLUMN_ID,
    SPANNING_COLUMN_ID,
    classify_block_column,
    detect_page_columns,
)


def _sort_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    return sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))


def _block_column_key(block: TextBlock, page_width: float) -> int:
    if block.column_id is not None:
        return block.column_id
    column = classify_block_column(block, page_width)
    if column == "RIGHT":
        return RIGHT_COLUMN_ID
    if column == "FULL_WIDTH":
        return SPANNING_COLUMN_ID
    return LEFT_COLUMN_ID


def order_page_blocks(page: PageExtraction) -> list[TextBlock]:
    """Column-major order: full-width top matter, left column, right column, full-width tail."""
    blocks = [b for b in page.blocks if b.type == "text" or b.text or b.type == "image"]
    if not blocks:
        return []

    page_columns = detect_page_columns(blocks, page.width)
    if page_columns == 1:
        return _sort_blocks(blocks)

    by_column: dict[int, list[TextBlock]] = {
        SPANNING_COLUMN_ID: [],
        LEFT_COLUMN_ID: [],
        RIGHT_COLUMN_ID: [],
    }
    for block in blocks:
        column_key = _block_column_key(block, page.width)
        by_column[column_key].append(block)

    full_width = _sort_blocks(by_column[SPANNING_COLUMN_ID])
    left = _sort_blocks(by_column[LEFT_COLUMN_ID])
    right = _sort_blocks(by_column[RIGHT_COLUMN_ID])

    if not left and not right:
        return full_width

    if not left or not right:
        return _sort_blocks(full_width + left + right)

    min_body_y = min(left[0].bbox[1], right[0].bbox[1])
    top_full = [b for b in full_width if b.bbox[1] < min_body_y - 2]
    tail_full = [b for b in full_width if b not in top_full]

    return top_full + left + right + tail_full


def order_document_blocks(pages: list[PageExtraction]) -> list[tuple[TextBlock, int]]:
    """Return (block, page_number) tuples in global reading order."""
    ordered: list[tuple[TextBlock, int]] = []
    for page in pages:
        for block in order_page_blocks(page):
            ordered.append((block, page.page_number))
    return ordered
