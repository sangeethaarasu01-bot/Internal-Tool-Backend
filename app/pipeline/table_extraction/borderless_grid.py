"""Build table grids from aligned text words (borderless / vector tables)."""

from __future__ import annotations

from collections import defaultdict

import pymupdf

from app.pipeline.table_extraction.postprocess import sanitize_cell


def _cluster_lines(words: list[tuple], y_tol: float = 4.0) -> list[list[tuple]]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[list[tuple]] = []
    current: list[tuple] = []
    current_y: float | None = None
    for w in sorted_words:
        y = w[1]
        if current_y is None or abs(y - current_y) <= y_tol:
            current.append(w)
            current_y = y if current_y is None else (current_y + y) / 2
        else:
            if current:
                lines.append(current)
            current = [w]
            current_y = y
    if current:
        lines.append(current)
    return lines


def _split_line_into_cells(line_words: list[tuple], gap_tol: float = 18.0) -> list[str]:
    line_words = sorted(line_words, key=lambda w: w[0])
    if not line_words:
        return []
    cells: list[str] = []
    buf: list[str] = [line_words[0][4]]
    prev_x1 = line_words[0][2]
    for w in line_words[1:]:
        if w[0] - prev_x1 > gap_tol:
            cells.append(" ".join(buf).strip())
            buf = [w[4]]
        else:
            buf.append(w[4])
        prev_x1 = w[2]
    cells.append(" ".join(buf).strip())
    return cells


def extract_borderless_grid(
    page: pymupdf.Page,
    bbox: list[float],
    *,
    caption_y_exclude: float | None = None,
) -> tuple[list[list[str]], list[float]]:
    """Return (rows, tight_bbox) from word alignment inside ``bbox``."""
    if len(bbox) < 4:
        return [], bbox
    clip = pymupdf.Rect(bbox)
    words = page.get_text("words", clip=clip)
    if not words:
        return [], bbox

    filtered: list[tuple] = []
    for w in words:
        if caption_y_exclude is not None and abs(w[1] - caption_y_exclude) < 8:
            continue
        filtered.append(w)

    lines = _cluster_lines(filtered)
    if len(lines) >= 2:
        line_ys = [sum(w[1] for w in ln) / len(ln) for ln in lines]
        trimmed: list[list[tuple]] = [lines[0]]
        for idx in range(1, len(lines)):
            gap = line_ys[idx] - line_ys[idx - 1]
            if gap > 32.0 and len(trimmed) >= 2:
                break
            trimmed.append(lines[idx])
        lines = trimmed

    row_cells: list[list[str]] = []
    y_coords: list[float] = []
    x_coords: list[float] = []

    for line in lines:
        cells = [_split_line_into_cells(line)]
        cells = cells[0] if cells else []
        if not any(c.strip() for c in cells):
            continue
        text_joined = " ".join(cells)
        upper = text_joined.upper()
        if upper.startswith("TABLE ") or upper.startswith("FIGURE "):
            continue
        if len(text_joined) > 150 and len(cells) <= 2:
            continue
        row_cells.append([sanitize_cell(c) for c in cells])
        y_coords.extend(w[1] for w in line)
        for w in line:
            x_coords.extend([w[0], w[2]])

    if len(row_cells) < 2:
        return [], bbox

    ncol_mode = max(len(r) for r in row_cells)
    if ncol_mode < 2:
        return [], bbox

    normalized: list[list[str]] = []
    for row in row_cells:
        if len(row) < ncol_mode:
            row = row + [""] * (ncol_mode - len(row))
        normalized.append(row[:ncol_mode])

    if not x_coords or not y_coords:
        return normalized, bbox

    tight = [
        min(x_coords),
        min(y_coords),
        max(x_coords),
        max(y_coords),
    ]
    return normalized, tight
