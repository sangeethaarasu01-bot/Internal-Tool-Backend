"""Step 4: Generic table cleanup and header detection."""

from __future__ import annotations

import re

HYPHEN_MERGE = re.compile(r"(\w)-\s+(\w)")
_NONE_LIKE = frozenset({"none", "nan", "null", "<na>"})
_TABLE_CAPTION_CELL_RE = re.compile(r"^TABLE\s+[IVX0-9]+[\.\:]", re.IGNORECASE)
_FIGURE_CAPTION_CELL_RE = re.compile(r"^FIG(?:URE)?\.?\s+[IVX0-9]+[\.\:]", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[\d{1,3}\]")
_SECTION_HEADING_CELL_RE = re.compile(
    r"^(?:[IVXLC]+\.|[0-9]+\.)\s+[A-ZÀ-ÖØ-Þ]",
)


def sanitize_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _NONE_LIKE:
        return ""
    return " ".join(text.replace("\n", " ").split())


def sanitize_rows(rows: list[list[str]]) -> list[list[str]]:
    return [[sanitize_cell(c) for c in row] for row in rows]


def strip_cells(rows: list[list[str]]) -> list[list[str]]:
    return sanitize_rows(rows)


def remove_empty_rows_cols(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []
    rows = strip_cells(rows)
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    padded = [r + [""] * (ncols - len(r)) for r in rows]
    keep_cols = [
        j
        for j in range(ncols)
        if any(padded[i][j] for i in range(len(padded)))
    ]
    return [[row[j] for j in keep_cols] for row in padded]


def fix_hyphenation(text: str) -> str:
    return HYPHEN_MERGE.sub(r"\1\2", text)


def _merge_row_cells(row: list[str]) -> list[str]:
    if not row:
        return row
    out: list[str] = []
    for cell in row:
        cell = fix_hyphenation(cell)
        if not out:
            out.append(cell)
            continue
        prev = out[-1]
        if prev.endswith("-") and cell and cell[0].islower():
            out[-1] = prev[:-1] + cell
            continue
        if prev.endswith(".") and cell and cell[0].islower():
            out[-1] = prev + " " + cell
            continue
        out.append(cell)
    return out


def merge_continuation_cells(rows: list[list[str]]) -> list[list[str]]:
    return [_merge_row_cells(row) for row in rows]


def detect_headers(rows: list[list[str]], first_row_bold_ratio: float = 0.0) -> tuple[list[str], list[list[str]]]:
    if not rows:
        return [], []
    rows = [list(r) for r in rows]
    if len(rows) == 1:
        return [], rows

    first = rows[0]
    if first_row_bold_ratio >= 0.5:
        return first, rows[1:]

    nonempty = [c for c in first if c]
    if nonempty and sum(len(c) for c in nonempty) / len(nonempty) < 30:
        return first, rows[1:]

    if nonempty and len(set(len(c) for c in nonempty)) == 1 and all(len(c) < 40 for c in nonempty):
        return first, rows[1:]

    return [], rows


def _is_body_text_row(row: list[str]) -> bool:
    cells = [sanitize_cell(c) for c in row if sanitize_cell(c)]
    if not cells:
        return True
    if all(len(c) < 2 for c in cells):
        return True
    if all(len(c) > 150 for c in cells):
        return True
    if len(cells) >= 2 and sum(len(c) for c in cells) / len(cells) > 90:
        return True
    joined = " ".join(cells)
    if _CITATION_RE.search(joined):
        return True
    if _SECTION_HEADING_CELL_RE.match(joined):
        return True
    if _TABLE_CAPTION_CELL_RE.match(joined) or _FIGURE_CAPTION_CELL_RE.match(joined):
        return True
    if "." in joined and len(joined) > 100:
        return True
    return False


def remove_body_text_rows(rows: list[list[str]]) -> tuple[list[list[str]], int]:
    kept: list[list[str]] = []
    removed = 0
    for row in rows:
        if _is_body_text_row(row):
            removed += 1
            continue
        kept.append(row)
    return kept, removed


def align_columns_to_header(
    headers: list[str],
    rows: list[list[str]],
) -> tuple[list[str], list[list[str]]]:
    if not headers:
        return headers, rows
    target = len(headers)
    if target < 1:
        return headers, rows
    out_rows: list[list[str]] = []
    for row in rows:
        row = list(row)
        if len(row) < target:
            row = row + [""] * (target - len(row))
        elif len(row) > target:
            head = row[: target - 1]
            tail = " ".join(sanitize_cell(c) for c in row[target - 1 :] if sanitize_cell(c))
            row = head + [tail]
        out_rows.append(row[:target])
    return headers, out_rows


def drop_caption_duplicate_rows(rows: list[list[str]]) -> list[list[str]]:
    cleaned: list[list[str]] = []
    for row in rows:
        joined = " ".join((c or "").strip() for c in row if (c or "").strip())
        if _TABLE_CAPTION_CELL_RE.match(joined):
            continue
        cleaned.append(row)
    return cleaned


def postprocess_table(
    rows: list[list[str]],
    *,
    first_row_bold_ratio: float = 0.0,
) -> tuple[list[str], list[list[str]], int]:
    rows = sanitize_rows(rows)
    rows = drop_caption_duplicate_rows(rows)
    rows = remove_empty_rows_cols(rows)
    rows, removed_body = remove_body_text_rows(rows)
    rows = merge_continuation_cells(rows)
    headers, body = detect_headers(rows, first_row_bold_ratio)
    headers, body = align_columns_to_header(headers, body)
    return headers, body, removed_body


def postprocess_table_legacy(
    rows: list[list[str]], *, first_row_bold_ratio: float = 0.0
) -> tuple[list[str], list[list[str]]]:
    headers, body, _ = postprocess_table(rows, first_row_bold_ratio=first_row_bold_ratio)
    return headers, body


def rows_to_raw_text(headers: list[str], rows: list[list[str]]) -> str:
    lines: list[str] = []
    if headers:
        lines.append("\t".join(headers))
    for row in rows:
        lines.append("\t".join(row))
    return "\n".join(lines)
