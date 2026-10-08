"""Reject Camelot-stream / full-page false positives (body text as tables)."""

from __future__ import annotations

from app.pipeline.table_extraction.geometry import bbox_height
from app.pipeline.table_extraction.postprocess import sanitize_rows
from app.pipeline.table_extraction.validate import cell_empty_ratio


def long_cell_count(rows: list[list[str]], threshold: int = 150) -> int:
    return sum(1 for row in rows for cell in row if len((cell or "").strip()) > threshold)


def average_cell_length(rows: list[list[str]]) -> float:
    cells = [(c or "").strip() for row in rows for c in row if (c or "").strip()]
    if not cells:
        return 0.0
    return sum(len(c) for c in cells) / len(cells)


def stream_candidate_reject_reason(
    rows: list[list[str]],
    bbox: list[float],
    *,
    page_height: float,
    caption_found: bool,
) -> str | None:
    rows = sanitize_rows(rows)
    if not rows:
        return "empty_grid"

    nrows = len(rows)
    ncols = max(len(r) for r in rows)

    if nrows > 30:
        return "too_many_rows"
    if ncols > 10:
        return "too_many_columns"
    if bbox_height(bbox) > 0.6 * page_height:
        return "bbox_too_tall"
    if long_cell_count(rows, 150) > 3:
        return "body_text_long_cells"
    if average_cell_length(rows) > 100:
        return "average_cell_too_long"
    if cell_empty_ratio(rows) > 0.55:
        return "too_many_empty_cells"
    return None
