"""OCR-based table extraction for PDFs where table cells lack a text layer.

Some IEEE proof PDFs render table content as vector paths or raster glyphs.
PyMuPDF ``find_tables()`` and text-block clustering cannot recover those cells.
This module renders the region below a table caption and reconstructs a grid
from OCR bounding boxes (RapidOCR when installed).
"""

from __future__ import annotations

import logging
import re
from statistics import median

import pymupdf

from app.models.extraction import ExtractedTable, TextBlock
from app.services.layout.semantic_patterns import TABLE_CAPTION_RE, first_line, normalize_text

logger = logging.getLogger(__name__)

_OCR_ENGINE = None

_NUMERIC_CELL_RE = re.compile(r"^-?\d*\.?\d+(?:[eE][+-]?\d+)?$")
_ROW_LABEL_RE = re.compile(r"^[A-Z]{1,3}\d+$", re.IGNORECASE)
_UNIT_SUFFIX_RE = re.compile(r"^\([^)]+\)$")

_MIN_OCR_SCORE = 0.5
_RENDER_SCALE = 3.0
_DEFAULT_TABLE_HEIGHT = 160.0
_MAX_TABLE_HEIGHT = 280.0


def _ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _bbox_overlap_x(a: list[float], b: list[float], min_overlap: float = 20.0) -> bool:
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    return overlap >= min_overlap


def _find_caption_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    captions: list[TextBlock] = []
    for block in blocks:
        if block.type != "text":
            continue
        line = first_line(normalize_text(block.text))
        if TABLE_CAPTION_RE.match(line):
            captions.append(block)
    return captions


def _next_block_bottom(blocks: list[TextBlock], caption: TextBlock) -> float | None:
    caption_bottom = caption.bbox[3]
    candidates = [
        block
        for block in blocks
        if block.block_id != caption.block_id
        and block.bbox[1] > caption_bottom + 4
        and _bbox_overlap_x(block.bbox, caption.bbox)
    ]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda item: item.bbox[1])
    return nearest.bbox[1] - 2


def _horizontal_rule_bounds(
    page: pymupdf.Page,
    top: float,
    bottom: float,
    caption_bbox: list[float],
) -> tuple[float, float]:
    x0 = caption_bbox[0] - 40.0
    x1 = caption_bbox[2] + 40.0
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.y0 < top - 6 or rect.y0 > bottom + 6:
            continue
        if rect.height > 4 or rect.width < 40:
            continue
        x0 = min(x0, rect.x0)
        x1 = max(x1, rect.x1)
    return x0, x1


def _estimate_table_rect(
    page: pymupdf.Page,
    caption: TextBlock,
    blocks: list[TextBlock],
) -> pymupdf.Rect | None:
    caption_bbox = caption.bbox
    table_top = caption_bbox[3] + 2.0
    prose_top = _next_block_bottom(blocks, caption)
    if prose_top is not None and prose_top > table_top + 20:
        table_bottom = prose_top
    else:
        table_bottom = min(page.rect.height, table_top + _DEFAULT_TABLE_HEIGHT)

    if table_bottom - table_top < 24:
        return None

    x0, x1 = _horizontal_rule_bounds(page, table_top, table_bottom, caption_bbox)
    width = x1 - x0
    if width < 80:
        x0 = max(page.rect.x0, caption_bbox[0] - 20)
        x1 = min(page.rect.x1, caption_bbox[2] + 120)

    height = table_bottom - table_top
    if height > _MAX_TABLE_HEIGHT:
        table_bottom = table_top + _MAX_TABLE_HEIGHT

    rect = pymupdf.Rect(x0, table_top, x1, table_bottom)
    if rect.width < 60 or rect.height < 20:
        return None
    return rect


def _cluster_values(values: list[float], tolerance: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [float(median(cluster)) for cluster in clusters]


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


def _ocr_items_to_grid(ocr_result: list) -> list[list[str]] | None:
    items: list[tuple[float, float, str]] = []
    for entry in ocr_result:
        if len(entry) < 3:
            continue
        box, text, score = entry[0], str(entry[1]).strip(), float(entry[2])
        if not text or score < _MIN_OCR_SCORE:
            continue
        cx = sum(point[0] for point in box) / 4.0
        cy = sum(point[1] for point in box) / 4.0
        items.append((cy, cx, text))

    if len(items) < 4:
        return None

    row_tolerance = max(12.0, median(item[0] for item in items) * 0.08)
    xs = sorted(item[1] for item in items)
    x_gaps = [xs[index + 1] - xs[index] for index in range(len(xs) - 1) if xs[index + 1] - xs[index] > 5]
    col_tolerance = max(24.0, median(x_gaps) * 0.6 if x_gaps else 40.0)

    row_centers = _cluster_values([item[0] for item in items], row_tolerance)
    col_centers = _cluster_values([item[1] for item in items], col_tolerance)
    if len(row_centers) < 2 or len(col_centers) < 2:
        return None

    grid: list[list[str]] = [[""] * len(col_centers) for _ in row_centers]
    for cy, cx, text in items:
        row_index = min(range(len(row_centers)), key=lambda idx: abs(cy - row_centers[idx]))
        col_index = min(range(len(col_centers)), key=lambda idx: abs(cx - col_centers[idx]))
        if grid[row_index][col_index]:
            grid[row_index][col_index] = f"{grid[row_index][col_index]} {text}".strip()
        else:
            grid[row_index][col_index] = text

    data_start = next((idx for idx, row in enumerate(grid) if _looks_like_data_row(row)), None)
    if data_start is None:
        return grid if len(grid) >= 2 and len(grid[0]) >= 2 else None
    if data_start == 0:
        return grid
    header_rows = grid[:data_start]
    data_rows = grid[data_start:]
    merged_header = _merge_header_rows(header_rows)
    if not any(cell.strip() for cell in merged_header):
        return None
    result = [merged_header] + data_rows
    if len(result) < 2 or not any(_looks_like_data_row(row) for row in data_rows):
        return None
    return result


def _ocr_table_region(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    engine,
) -> list[list[str]] | None:
    matrix = pymupdf.Matrix(_RENDER_SCALE, _RENDER_SCALE)
    pixmap = page.get_pixmap(clip=rect, matrix=matrix)
    image_bytes = pixmap.tobytes("png")
    result, _elapsed = engine(image_bytes)
    if not result:
        return None
    return _ocr_items_to_grid(result)


def extract_ocr_tables_from_page(
    page: pymupdf.Page,
    page_number: int,
    blocks: list[TextBlock],
    *,
    engine=None,
) -> list[ExtractedTable]:
    """Extract tables rendered without a text layer using OCR below captions."""
    ocr = engine if engine is not None else _ocr_engine()
    if ocr is None:
        return []

    tables: list[ExtractedTable] = []
    for index, caption in enumerate(_find_caption_blocks(blocks)):
        rect = _estimate_table_rect(page, caption, blocks)
        if rect is None:
            continue
        rows = _ocr_table_region(page, rect, ocr)
        if not rows or len(rows) < 2:
            continue
        tables.append(
            ExtractedTable(
                table_id=f"p{page_number}_ocr{index}",
                page_number=page_number,
                rows=rows,
                bbox=[float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)],
            )
        )
    return tables
