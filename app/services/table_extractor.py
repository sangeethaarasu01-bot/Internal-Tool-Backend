"""Extract table grids from PDF pages using PyMuPDF and OCR fallbacks."""

from __future__ import annotations

from typing import Any

import pymupdf

from app.models.extraction import ExtractedTable, TextBlock
from app.services.table_ocr_extractor import extract_ocr_tables_from_page

_STRATEGIES = (None, "lines", "lines_strict")


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split()).strip()


def _table_from_pymupdf(page: pymupdf.Page, page_number: int, table, index: int) -> ExtractedTable | None:
    data = table.extract() or []
    rows = [[_clean_cell(cell) for cell in row] for row in data if row]
    if len(rows) < 2:
        return None
    bbox = None
    try:
        rect = table.bbox
        bbox = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
    except Exception:
        bbox = None
    return ExtractedTable(
        table_id=f"p{page_number}_t{index}",
        page_number=page_number,
        rows=rows,
        bbox=bbox,
    )


def _extract_pymupdf_tables(page: pymupdf.Page, page_number: int) -> list[ExtractedTable]:
    tables: list[ExtractedTable] = []
    seen_bboxes: list[list[float]] = []

    for strategy in _STRATEGIES:
        try:
            finder = page.find_tables(strategy=strategy) if strategy else page.find_tables()
            raw_tables = finder.tables if finder else []
        except Exception:
            continue

        for table in raw_tables:
            try:
                rect = table.bbox
                width = rect.x1 - rect.x0
                height = rect.y1 - rect.y0
                if width > page.rect.width * 0.92 and height > page.rect.height * 0.75:
                    continue
            except Exception:
                pass

            extracted = _table_from_pymupdf(page, page_number, table, len(tables))
            if extracted is None or extracted.bbox is None:
                continue
            if any(_bbox_similar(extracted.bbox, existing) for existing in seen_bboxes):
                continue
            seen_bboxes.append(extracted.bbox)
            tables.append(extracted)
    return tables


def _bbox_similar(a: list[float], b: list[float], tolerance: float = 8.0) -> bool:
    return all(abs(a[i] - b[i]) <= tolerance for i in range(4))


def extract_tables_from_page(
    page: pymupdf.Page,
    page_number: int,
    blocks: list[TextBlock] | None = None,
) -> tuple[list[ExtractedTable], bool]:
    """Return table grids detected on a single page and whether OCR was used."""
    tables = _extract_pymupdf_tables(page, page_number)
    ocr_applied = False

    if blocks:
        ocr_tables = extract_ocr_tables_from_page(page, page_number, blocks)
        for ocr_table in ocr_tables:
            if ocr_table.bbox and any(_bbox_similar(ocr_table.bbox, existing.bbox or []) for existing in tables if existing.bbox):
                continue
            tables.append(ocr_table)
            ocr_applied = True

    return tables, ocr_applied
