"""Two-column aware reading order reconstruction."""

from __future__ import annotations

from app.models.extraction import PageExtraction, TextBlock
from app.services.layout.column_classifier import classify_block_column


def _sort_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    return sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))


def _interleave_columns(left: list[TextBlock], right: list[TextBlock]) -> list[TextBlock]:
    """Read two body columns row-by-row (top-to-bottom within each visual row)."""
    ordered: list[TextBlock] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_y = left[left_index].bbox[1]
        right_y = right[right_index].bbox[1]
        if left_y <= right_y + 2:
            ordered.append(left[left_index])
            left_index += 1
        else:
            ordered.append(right[right_index])
            right_index += 1
    ordered.extend(left[left_index:])
    ordered.extend(right[right_index:])
    return ordered


def order_page_blocks(page: PageExtraction) -> list[TextBlock]:
    """Column-major order: full-width top matter, left column, right column, full-width tail."""
    blocks = [b for b in page.blocks if b.type == "text" or b.text or b.type == "image"]
    if not blocks:
        return []

    by_column: dict[str, list[TextBlock]] = {"FULL_WIDTH": [], "LEFT": [], "RIGHT": []}
    for block in blocks:
        column = classify_block_column(block, page.width)
        by_column[column].append(block)

    full_width = _sort_blocks(by_column["FULL_WIDTH"])
    left = _sort_blocks(by_column["LEFT"])
    right = _sort_blocks(by_column["RIGHT"])

    if not left and not right:
        return full_width

    if not left or not right:
        return _sort_blocks(full_width + left + right)

    min_body_y = min(left[0].bbox[1], right[0].bbox[1])
    top_full = [b for b in full_width if b.bbox[1] < min_body_y - 2]
    tail_full = [b for b in full_width if b not in top_full]

    ordered = top_full + _interleave_columns(left, right) + tail_full
    return ordered


def order_document_blocks(pages: list[PageExtraction]) -> list[tuple[TextBlock, int]]:
    """Return (block, page_number) tuples in global reading order."""
    ordered: list[tuple[TextBlock, int]] = []
    for page in pages:
        for block in order_page_blocks(page):
            ordered.append((block, page.page_number))
    return ordered
