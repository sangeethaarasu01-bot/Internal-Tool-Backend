"""Generic table candidate quality scoring."""

from __future__ import annotations

import re

from app.pipeline.table_extraction.geometry import bbox_area, bbox_height, overlap_ratio_of_a
from app.pipeline.table_extraction.postprocess import sanitize_rows
from app.pipeline.table_extraction.types import PageIngest

_NUMERIC_CELL = re.compile(r"\d")


def _row_col_stats(rows: list[list[str]]) -> tuple[int, int, float, float]:
    rows = sanitize_rows(rows)
    if not rows:
        return 0, 0, 0.0, 0.0
    nrows = len(rows)
    ncols = max(len(r) for r in rows)
    cells = [c for row in rows for c in row]
    nonempty = sum(1 for c in cells if (c or "").strip())
    fill = nonempty / len(cells) if cells else 0.0
    lengths = [len((c or "").strip()) for c in cells if (c or "").strip()]
    avg_len = sum(lengths) / len(lengths) if lengths else 0.0
    return nrows, ncols, fill, avg_len


def _column_uniformity(rows: list[list[str]]) -> float:
    rows = sanitize_rows(rows)
    if not rows:
        return 0.0
    ncols = max(len(r) for r in rows)
    if ncols < 2:
        return 0.0
    counts = [sum(1 for r in rows if len(r) > j and (r[j] or "").strip()) for j in range(ncols)]
    if not counts:
        return 0.0
    mean = sum(counts) / len(counts)
    if mean <= 0:
        return 0.0
    var = sum((c - mean) ** 2 for c in counts) / len(counts)
    return max(0.0, 1.0 - (var ** 0.5) / mean)


def _numeric_content_ratio(rows: list[list[str]]) -> float:
    cells = [(c or "").strip() for row in rows for c in row if (c or "").strip()]
    if not cells:
        return 0.0
    with_digit = sum(1 for c in cells if _NUMERIC_CELL.search(c))
    return with_digit / len(cells)


def score_candidate(
    rows: list[list[str]],
    bbox: list[float],
    page: PageIngest,
    *,
    caption_nearby: bool,
    figure_regions: list[list[float]],
) -> tuple[float, list[str], str | None]:
    """Return (score 0-1, positive signals, reject_reason or None)."""
    signals: list[str] = []
    nrows, ncols, fill, avg_len = _row_col_stats(rows)

    if nrows < 2 or ncols < 2:
        return 0.0, signals, "row_or_column_count_too_low"

    page_area = page.page_width * page.page_height
    area = bbox_area(bbox)
    if area < 2000:
        return 0.0, signals, "bbox_too_small"

    if area > 0.88 * page_area:
        return 0.0, signals, "bbox_covers_page"

    if bbox_height(bbox) > 0.72 * page.page_height and nrows > 12:
        return 0.0, signals, "bbox_too_tall"

    if ncols > 14:
        return 0.0, signals, "column_count_too_high"

    for region in figure_regions:
        if overlap_ratio_of_a(bbox, region) > 0.55:
            return 0.0, signals, "figure_overlap"

    score = 0.18
    if caption_nearby:
        score += 0.18
        signals.append("caption_nearby")
    if nrows >= 3:
        score += 0.08
        signals.append("multi_row")
    if ncols >= 2:
        score += 0.06
    score += min(0.22, fill * 0.28)
    if fill > 0.35:
        signals.append("reasonable_fill")

    uniformity = _column_uniformity(rows)
    score += uniformity * 0.12
    if uniformity > 0.6:
        signals.append("uniform_columns")

    num_ratio = _numeric_content_ratio(rows)
    score += min(0.12, num_ratio * 0.15)

    if avg_len > 140 and ncols <= 3:
        score -= 0.15
    if avg_len > 200:
        score -= 0.1

    if fill < 0.12:
        score -= 0.2

    score = max(0.0, min(1.0, score))
    return score, signals, None
