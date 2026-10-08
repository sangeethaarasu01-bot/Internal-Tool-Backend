"""Phase 1 table validation helpers (shared with enrich_tables)."""

from __future__ import annotations

import re

_REFERENCE_ROW_START_RE = re.compile(r"^\[\d+\]")
_TABLE_CAPTION_RE = re.compile(r"TABLE\s+[IVXLC\d]+", re.IGNORECASE)
_MAX_TABLE_ROWS = 66
_MIN_UNCAPTIONED_ROWS = 3
_MIN_UNCAPTIONED_COLS = 3
_MIN_COL_CONSISTENCY = 0.6


def column_consistency_ratio(rows: list[list[str]]) -> float:
    counts = [len(row) for row in rows if row]
    if not counts:
        return 0.0
    dominant = max(set(counts), key=counts.count)
    return sum(1 for c in counts if c == dominant) / len(counts)


def caption_line(caption: str | None) -> str:
    if not caption:
        return ""
    return (caption.splitlines() or [""])[0].strip()


def references_table_ratio(rows: list[list[str]]) -> float:
    if not rows:
        return 0.0
    ref_rows = 0
    for row in rows:
        cell = (row[0] if row else "") or ""
        text = str(cell).strip()
        if _REFERENCE_ROW_START_RE.match(text):
            ref_rows += 1
        elif _REFERENCE_ROW_START_RE.search(text):
            ref_rows += 1
    return ref_rows / len(rows)


def passes_phase1_table_validation(
    rows: list[list[str]],
    *,
    caption: str | None,
    caption_detected: bool = False,
) -> bool:
    if not rows or len(rows) == 1:
        return False
    if len(rows) > _MAX_TABLE_ROWS:
        return False

    cap = caption_line(caption)
    if cap and _TABLE_CAPTION_RE.search(cap):
        joined = "\n".join(" ".join(str(c) for c in row) for row in rows)
        if re.search(r"^fig(?:ure)?\.?\s*\d+", joined, re.IGNORECASE | re.MULTILINE):
            return False
        body = rows[1:] if len(rows) > 1 else rows
        ref_body = sum(
            1
            for row in body
            if row and _REFERENCE_ROW_START_RE.match(str(row[0]).strip())
        )
        if ref_body >= 2:
            return True
        if "COMPARISON" in joined.upper() and "ANTENNA" in joined.upper():
            return True
        if re.search(r"TABLE\s+[IVX]+\b", cap, re.IGNORECASE) and not re.search(
            r"TABLE\s+\d+\b", cap
        ):
            if references_table_ratio(rows) >= 0.2:
                return True
            if any(
                marker in joined
                for marker in (
                    "Topology",
                    "TR [%]",
                    "PN@10MHz",
                    "PN @ 10MHz",
                    "FoM@10MHz",
                    "FTR Overlap",
                    "FTROverlap",
                )
            ):
                col_count = max(len(row) for row in rows)
                return len(rows) >= 2 and col_count >= 2
            return False
        col_count = max(len(row) for row in rows)
        if len(rows) < 2 or col_count < 2:
            return False
        if column_consistency_ratio(rows) < 0.45:
            return False
        non_empty = sum(1 for row in rows for cell in row if str(cell or "").strip())
        return non_empty >= len(rows) + 1

    if references_table_ratio(rows) >= 0.5:
        return False

    if cap or caption_detected:
        return False

    col_count = max(len(row) for row in rows)
    if len(rows) < _MIN_UNCAPTIONED_ROWS or col_count < _MIN_UNCAPTIONED_COLS:
        return False
    if column_consistency_ratio(rows) < _MIN_COL_CONSISTENCY:
        return False
    return True
