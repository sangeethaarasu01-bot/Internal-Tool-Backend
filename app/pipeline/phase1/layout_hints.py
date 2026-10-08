"""Page layout hints for Phase 1 (multi-column detection, paragraph grouping)."""

from __future__ import annotations

from app.models.document_structure import ProcessedBlock
from app.models.extracted_document import ColumnLayoutKind
from app.models.extraction import ExtractionResult, TextBlock
from app.services.layout.column_classifier import classify_block_column
from app.services.layout.reading_order import order_page_blocks

PARAGRAPH_GAP_TOLERANCE = 6.0


def page_column_layout(page_width: float, blocks: list[TextBlock]) -> ColumnLayoutKind:
    columns = {classify_block_column(block, page_width) for block in blocks if block.type == "text"}
    columns.discard("FULL_WIDTH")
    if "LEFT" in columns and "RIGHT" in columns:
        return "two_column"
    if columns:
        return "single"
    return "unknown"


def multi_column_pages(raw: ExtractionResult, processed: list[ProcessedBlock]) -> list[int]:
    by_page: dict[int, set[str]] = {}
    for block in processed:
        if block.exclude_from_content:
            continue
        by_page.setdefault(block.page_number, set()).add(block.column)
    pages: list[int] = []
    for page in raw.pages:
        cols = by_page.get(page.page_number, set())
        if "LEFT" in cols and "RIGHT" in cols:
            pages.append(page.page_number)
        elif page_column_layout(page.width, page.blocks) == "two_column":
            pages.append(page.page_number)
    return sorted(set(pages))


def group_paragraph_block_ids(page_number: int, processed: list[ProcessedBlock]) -> list[list[str]]:
    """Group consecutive body paragraphs in reading order on one page."""
    page_blocks = [
        b
        for b in sorted(processed, key=lambda x: x.reading_order_index)
        if b.page_number == page_number
        and not b.exclude_from_content
        and b.classification in {"PARAGRAPH", "BODY_TEXT", "ABSTRACT"}
        and (b.text or "").strip()
    ]
    groups: list[list[str]] = []
    current: list[str] = []
    last_bottom: float | None = None
    last_column: str | None = None

    for block in page_blocks:
        if len(block.bbox) < 4:
            if current:
                groups.append(current)
                current = []
            continue
        top = block.bbox[1]
        if (
            current
            and last_bottom is not None
            and last_column == block.column
            and top - last_bottom <= PARAGRAPH_GAP_TOLERANCE
        ):
            current.append(block.block_id)
        else:
            if current:
                groups.append(current)
            current = [block.block_id]
        last_bottom = block.bbox[3]
        last_column = block.column

    if current:
        groups.append(current)
    return groups
