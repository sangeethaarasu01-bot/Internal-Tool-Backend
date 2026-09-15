"""Reconstruct table grids from positioned text blocks when PyMuPDF find_tables() fails.

IEEE-style tables are often borderless; ``page.find_tables()`` frequently returns nothing.
This module clusters caption-adjacent blocks by row/column geometry into a cell grid.
"""

from __future__ import annotations

import re
from statistics import median

from app.models.document_structure import ProcessedBlock
from app.services.layout.semantic_patterns import normalize_text

_NUMERIC_CELL_RE = re.compile(r"^-?\d*\.?\d+(?:[eE][+-]?\d+)?$")
_ROW_LABEL_RE = re.compile(r"^[A-Z]{1,3}\d+$", re.IGNORECASE)

TABLE_STOP_SEMANTIC_TYPES = frozenset(
    {
        "SECTION",
        "SUBSECTION",
        "TABLE_CAPTION",
        "FIGURE_CAPTION",
        "FIGURE",
        "REFERENCE",
        "REFERENCE_LIST",
        "JOURNAL_HEADER",
        "RUNNING_HEADER",
        "PAGE_NUMBER",
        "FOOTER",
        "TITLE",
        "ABSTRACT",
        "KEYWORDS",
    }
)

_MAX_TABLE_CELL_CHARS = 80
_MAX_TABLE_CELL_WORDS = 10

EnrichedItem = tuple[ProcessedBlock, str, float, str | None, object]


def _block_center_x(block: ProcessedBlock) -> float:
    return (block.bbox[0] + block.bbox[2]) / 2.0


def _block_top(block: ProcessedBlock) -> float:
    return block.bbox[1]


def _block_height(block: ProcessedBlock) -> float:
    return max(4.0, block.bbox[3] - block.bbox[1])


def _cluster_x_centers(centers: list[float], tolerance: float) -> list[float]:
    if not centers:
        return []
    sorted_centers = sorted(centers)
    clusters: list[list[float]] = [[sorted_centers[0]]]
    for x in sorted_centers[1:]:
        if x - clusters[-1][-1] <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [float(median(cluster)) for cluster in clusters]


def _cluster_rows(blocks: list[ProcessedBlock], row_tolerance: float) -> list[list[ProcessedBlock]]:
    if not blocks:
        return []
    ordered = sorted(blocks, key=_block_top)
    rows: list[list[ProcessedBlock]] = [[ordered[0]]]
    anchor_y = _block_top(ordered[0])
    for block in ordered[1:]:
        y = _block_top(block)
        if y - anchor_y <= row_tolerance:
            rows[-1].append(block)
        else:
            rows.append([block])
            anchor_y = y
    return rows


def _assign_row_to_columns(
    row_blocks: list[ProcessedBlock],
    column_centers: list[float],
) -> list[str]:
    cells = [""] * len(column_centers)
    for block in sorted(row_blocks, key=lambda item: item.bbox[0]):
        text = normalize_text(block.text)
        if not text:
            continue
        cx = _block_center_x(block)
        column_index = min(range(len(column_centers)), key=lambda idx: abs(cx - column_centers[idx]))
        if cells[column_index]:
            cells[column_index] = f"{cells[column_index]} {text}".strip()
        else:
            cells[column_index] = text
    return cells


def _looks_like_data_row(cells: list[str]) -> bool:
    non_empty = [cell for cell in cells if cell.strip()]
    if len(non_empty) < 2:
        return False
    first = non_empty[0].strip()
    numeric_cells = sum(1 for cell in non_empty[1:] if _NUMERIC_CELL_RE.match(cell.strip()))
    if _ROW_LABEL_RE.match(first):
        return numeric_cells >= max(1, len(non_empty) - 1)
    return numeric_cells >= max(1, (len(non_empty) - 1) // 2)


def _merge_header_rows(header_rows: list[list[str]]) -> list[str]:
    if not header_rows:
        return []
    width = max(len(row) for row in header_rows)
    merged = [""] * width
    for row in header_rows:
        for index, cell in enumerate(row):
            if index >= width:
                continue
            value = cell.strip()
            if not value:
                continue
            if merged[index]:
                merged[index] = f"{merged[index]} {value}".strip()
            else:
                merged[index] = value
    return merged


def reconstruct_table_grid_from_blocks(blocks: list[ProcessedBlock]) -> list[list[str]] | None:
    """Build a row/column grid from geometrically aligned text blocks.

    Returns ``None`` when the blocks do not form a plausible table (too few rows/columns).
    """
    usable = [block for block in blocks if normalize_text(block.text)]
    if len(usable) < 4:
        return None

    row_tolerance = max(6.0, median(_block_height(block) for block in usable) * 0.65)
    col_tolerance = max(
        18.0,
        median(max(8.0, block.bbox[2] - block.bbox[0]) for block in usable) * 0.75,
    )

    physical_rows = _cluster_rows(usable, row_tolerance)
    if len(physical_rows) < 2:
        return None

    column_centers = _cluster_x_centers(
        [_block_center_x(block) for block in usable],
        col_tolerance,
    )
    if len(column_centers) < 2:
        return None

    grid_rows = [_assign_row_to_columns(row_blocks, column_centers) for row_blocks in physical_rows]

    data_start = next((idx for idx, row in enumerate(grid_rows) if _looks_like_data_row(row)), None)
    if data_start is None:
        if len(grid_rows) < 2:
            return None
        header_rows = grid_rows[:-1]
        data_rows = grid_rows[-1:]
        if len(data_rows[0]) < 2:
            return None
    elif data_start == 0:
        return grid_rows if len(grid_rows) >= 2 and len(grid_rows[0]) >= 2 else None
    else:
        header_rows = grid_rows[:data_start]
        data_rows = grid_rows[data_start:]

    merged_header = _merge_header_rows(header_rows)
    if not any(cell.strip() for cell in merged_header):
        return None

    result = [merged_header] + data_rows
    if len(result) < 2 or len(merged_header) < 2:
        return None
    if not any(_looks_like_data_row(row) for row in data_rows):
        return None
    return result


def _collection_gap_limit(candidates: list[ProcessedBlock]) -> float:
    if not candidates:
        return 36.0
    return max(18.0, median(_block_height(block) for block in candidates) * 2.5)


def _is_plausible_table_cell(block: ProcessedBlock, sem_type: str) -> bool:
    """Return True when a block below a caption is likely table content, not prose."""
    if sem_type in TABLE_STOP_SEMANTIC_TYPES:
        return False
    text = normalize_text(block.text)
    if not text:
        return False
    if len(text) > _MAX_TABLE_CELL_CHARS:
        return False
    if sem_type == "PARAGRAPH" and len(text.split()) > _MAX_TABLE_CELL_WORDS:
        return False
    return True


def collect_table_blocks_after_caption(
    caption_block: ProcessedBlock,
    enriched: list[EnrichedItem],
    start_index: int,
) -> tuple[list[ProcessedBlock], int]:
    """Return text blocks belonging to the table immediately below ``caption_block``.

    The returned consume count is how many enriched items after ``start_index`` were absorbed.
    """
    candidates: list[ProcessedBlock] = []
    consumed = 0
    caption_bottom = caption_block.bbox[3]
    last_bottom = caption_bottom

    index = start_index + 1
    while index < len(enriched):
        block, sem_type, _confidence, _reason, _marker = enriched[index]
        if block.page_number != caption_block.page_number:
            break
        if block.exclude_from_content:
            index += 1
            continue
        if not _is_plausible_table_cell(block, sem_type):
            break

        block_top = block.bbox[1]
        if block_top + 2 < caption_bottom:
            index += 1
            continue

        if candidates:
            gap = block_top - last_bottom
            if gap > _collection_gap_limit(candidates):
                break

        text = normalize_text(block.text)
        if not text:
            index += 1
            continue

        candidates.append(block)
        last_bottom = max(last_bottom, block.bbox[3])
        consumed += 1
        index += 1

    return candidates, consumed
