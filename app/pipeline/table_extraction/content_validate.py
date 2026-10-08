"""Post-extraction content sanity checks for table grids."""

from __future__ import annotations

import re

from app.pipeline.table_extraction.postprocess import sanitize_rows

_CAPTION_CELL = re.compile(r"^(?:TABLE|FIG(?:URE)?)\s+[IVX0-9]+", re.IGNORECASE)
_CITATION = re.compile(r"\[\d{1,3}\]")
_LONG_SENTENCE = re.compile(r".{100,}\..+")


def validate_emitted_table_content(
    headers: list[str],
    rows: list[list[str]],
) -> str | None:
    headers = sanitize_rows([headers])[0] if headers else []
    rows = sanitize_rows(rows)
    body = rows
    row_count = len(body) + (1 if headers else 0)
    if row_count < 2:
        return "too_few_rows"
    if row_count > 22:
        return "too_many_rows"

    hcols = len(headers) if headers else 0
    if hcols:
        for row in body:
            if len(row) > hcols + 2:
                return "column_count_mismatch"

    for row in ([headers] if headers else []) + body:
        cells = [str(c or "").strip() for c in row if str(c or "").strip()]
        if not cells:
            continue
        if all(len(c) > 150 for c in cells):
            return "body_text_row"
        joined = " ".join(cells)
        if _CITATION.search(joined):
            return "citation_in_cell"
        if _CAPTION_CELL.match(joined):
            return "caption_in_cell"
        if _LONG_SENTENCE.match(joined):
            return "prose_in_cell"
    return None
