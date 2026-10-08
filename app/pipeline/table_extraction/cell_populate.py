"""Fill empty table grids from OCR / borderless text when structure engines miss text."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.pipeline.table_extraction.borderless_grid import extract_borderless_grid
from app.pipeline.table_extraction.ocr_grid import ocr_bbox_to_grid
from app.pipeline.table_extraction.postprocess import sanitize_rows
from app.pipeline.table_extraction.types import PageIngest, RawDetectedTable


def cell_fill_ratio(rows: list[list[str]]) -> float:
    rows = sanitize_rows(rows)
    if not rows:
        return 0.0
    ncols = max(len(r) for r in rows)
    total = len(rows) * ncols
    if total <= 0:
        return 0.0
    nonempty = sum(1 for row in rows for cell in row if str(cell or "").strip())
    return nonempty / total


def enrich_raw_table_cells(
    pdf_path: Path,
    page: PageIngest,
    raw: RawDetectedTable,
    *,
    caption_bbox: list[float] | None = None,
    min_improvement: float = 0.08,
) -> RawDetectedTable:
    """Replace or upgrade grid cells when fill is low (e.g. img2table structure-only)."""
    current_fill = cell_fill_ratio(raw.rows)
    if current_fill >= 0.22:
        return raw
    if len(raw.bbox) < 4:
        return raw

    doc = pymupdf.open(str(pdf_path))
    try:
        pymupdf_page = doc[page.page_number - 1]
        cap_y = caption_bbox[1] if caption_bbox and len(caption_bbox) >= 4 else None

        best_rows = sanitize_rows(raw.rows)
        best_bbox = list(raw.bbox)
        best_fill = current_fill
        best_engine = raw.engine

        candidates: list[tuple[str, list[list[str]], list[float]]] = []

        ocr_rows, ocr_bbox = ocr_bbox_to_grid(pymupdf_page, raw.bbox)
        if ocr_rows:
            candidates.append(("ocr-grid", ocr_rows, ocr_bbox if len(ocr_bbox) >= 4 else raw.bbox))

        bl_rows, bl_bbox = extract_borderless_grid(
            pymupdf_page,
            raw.bbox,
            caption_y_exclude=cap_y,
        )
        if bl_rows:
            candidates.append(
                (
                    "borderless-grid",
                    bl_rows,
                    bl_bbox if len(bl_bbox) >= 4 else raw.bbox,
                )
            )

        for engine, rows, bbox in candidates:
            fill = cell_fill_ratio(rows)
            if fill > best_fill + min_improvement or (
                fill > best_fill and best_fill < 0.12
            ):
                best_rows = sanitize_rows(rows)
                best_bbox = list(bbox)
                best_fill = fill
                best_engine = engine
    finally:
        doc.close()

    if best_fill <= current_fill + 0.02:
        return raw

    return RawDetectedTable(
        rows=best_rows,
        bbox=best_bbox,
        engine=best_engine,
        page_number=raw.page_number,
        bound_caption=raw.bound_caption,
    )
