"""Validation and phantom filtering using quality scoring."""



from __future__ import annotations



from typing import Literal



from app.pipeline.table_extraction.geometry import bbox_area, bbox_height

from app.pipeline.table_extraction.postprocess import sanitize_rows

from app.pipeline.table_extraction.types import EngineName



MIN_BBOX_AREA = 2000.0





def _cell_text(cell: object) -> str:

    return str(cell or "").strip()





def _column_width_irregularity(rows: list[list[str]]) -> float:

    """Proxy for column width spread using max text length per column."""

    rows = sanitize_rows(rows)

    if not rows:

        return 1.0

    ncols = max(len(r) for r in rows)

    if ncols < 2:

        return 1.0

    widths: list[float] = []

    for j in range(ncols):

        w = max(len(_cell_text(row[j] if j < len(row) else "")) for row in rows)

        widths.append(float(w) if w > 0 else 1.0)

    mn = min(widths)

    mx = max(widths)

    if mn <= 0:

        return mx

    return mx / mn





def is_phantom(rows: list[list[str]], bbox: list[float] | None = None) -> bool:

    rows = sanitize_rows(rows)

    if not rows:

        return True

    nrows = len(rows)

    ncols = max(len(r) for r in rows) if rows else 0

    if nrows < 2 or ncols < 2:

        return True

    if bbox is not None and len(bbox) >= 4 and bbox_area(bbox) < MIN_BBOX_AREA:

        return True

    if ncols > 22:

        return True

    cells = [c for row in rows for c in row]

    if not cells:

        return True

    if all(not _cell_text(c) for c in cells):

        return True

    if all(_only_whitespace_punct(c) for c in cells):

        return True

    empty_r = cell_empty_ratio(rows)

    if empty_r > 0.60 and nrows >= 3 and ncols >= 3:

        return True

    if ncols >= 4 and _column_width_irregularity(rows) > 10.0:

        return True

    return False





def _only_whitespace_punct(s: str) -> bool:

    s = _cell_text(s)

    if not s:

        return True

    return all(not ch.isalnum() for ch in s)





def cell_empty_ratio(rows: list[list[str]]) -> float:

    rows = sanitize_rows(rows)

    cells = [c for row in rows for c in row]

    if not cells:

        return 1.0

    empty = sum(1 for c in cells if not _cell_text(c))

    return empty / len(cells)





def validate_table(

    headers: list[str],

    rows: list[list[str]],

    bbox: list[float],

    figure_regions: list[list[float]],

    *,

    page_height: float,

    page_width: float,

    caption_detected: bool,

    quality_score: float,

) -> tuple[Literal["structured", "partial", "rejected"], str | None, list[str]]:

    warnings: list[str] = []

    headers = sanitize_rows([headers])[0] if headers else []

    rows = sanitize_rows(rows)

    all_rows = ([headers] + rows) if headers else rows

    nrows = len(all_rows)

    ncols = max(len(r) for r in all_rows) if all_rows else 0



    if nrows < 2 or ncols < 2:

        return "rejected", "row_or_column_count_too_low", warnings



    if bbox_area(bbox) < MIN_BBOX_AREA:

        return "rejected", "bbox_too_small", warnings



    if bbox_area(bbox) > 0.9 * page_width * page_height:

        return "rejected", "bbox_covers_page", warnings



    if bbox_height(bbox) > 0.75 * page_height and nrows > 15:

        return "rejected", "bbox_too_tall", warnings



    if ncols >= 4 and _column_width_irregularity(all_rows) > 10.0:

        return "rejected", "column_width_irregular", warnings



    empty_r = cell_empty_ratio(all_rows)

    if empty_r > 0.60 and nrows >= 3 and ncols >= 3 and not caption_detected:

        return "rejected", "empty_cells_ratio_too_high", warnings



    if not caption_detected:

        warnings.append("caption_not_matched")



    if empty_r > 0.45 or quality_score < 0.30:

        if empty_r > 0.45:

            warnings.append("moderate_empty_cell_ratio")

        if quality_score < 0.30:

            warnings.append("moderate_quality_score")

        return "partial", None, warnings



    if quality_score < 0.45:

        return "partial", None, warnings



    return "structured", None, warnings





def extraction_confidence(

    *,

    status: str,

    engine: EngineName,

    caption_detected: bool,

    empty_ratio: float,

    quality_score: float = 0.5,

) -> float:

    base = {

        "camelot-lattice": 0.92,

        "camelot-stream": 0.78,

        "img2table": 0.72,

        "pymupdf": 0.65,

        "pdfplumber": 0.55,

        "borderless-grid": 0.7,

        "ocr-grid": 0.68,

    }.get(engine, 0.5)

    base = 0.55 * base + 0.45 * quality_score

    if status == "rejected":

        return max(0.1, base * 0.35)

    if status == "partial":

        base *= 0.85

    base *= 1.0 - empty_ratio * 0.35

    if caption_detected:

        base = min(1.0, base + 0.05)

    return round(min(1.0, max(0.0, base)), 3)


