#!/usr/bin/env python3
"""
Apply manual table corrections from table_corrections.json to extraction output.json.

Replaces broken table fields (caption, headers, rows, counts, raw_text) and marks
extraction_quality as manually corrected. Writes output_fixed.json.

Usage:
    python fix_all_tables.py [output.json] [table_corrections.json] [output_fixed.json]
    python fix_all_tables.py --fix-captions [output.json]

Options:
    --fix-captions  Set caption on specific table_ids when caption is null/empty;
                    saves the input JSON back in place (UTF-8, indent=2).

Defaults (same directory as this script):
    output.json, table_corrections.json, output_fixed.json
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Applied with --fix-captions only when caption is null or empty.
CAPTION_ONLY_FIXES: dict[str, str] = {
    "p13_ocr1": "TABLE 6. Operational trade-offs in the combined cycle.",
    "p14_ocr0": "TABLE 7. Summary of V-cycle measurements (8 loading cycles).",
    "p14_ocr1": "TABLE 8. Summary of the combined cycle measurements.",
}


def _parse_argv(argv: list[str]) -> tuple[bool, list[str]]:
    """Return (fix_captions_flag, positional_args_without_flag)."""
    fix_captions = "--fix-captions" in argv[1:]
    positional = [arg for arg in argv[1:] if arg != "--fix-captions"]
    return fix_captions, positional


def _caption_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _apply_caption_only_fixes(
    by_id: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """
    Fill captions from CAPTION_ONLY_FIXES when missing.

    Returns (updated_ids, skipped_nonempty_ids, missing_ids).
    """
    updated: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    for tid, caption in CAPTION_ONLY_FIXES.items():
        table = by_id.get(tid)
        if table is None:
            missing.append(tid)
            continue
        if _caption_is_empty(table.get("caption")):
            table["caption"] = caption
            updated.append(tid)
        else:
            skipped.append(tid)
    return updated, skipped, missing


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _table_id(table: dict[str, Any]) -> str | None:
    tid = table.get("table_id") or table.get("id")
    if tid is None:
        return None
    return str(tid)


def _dimensions(table: dict[str, Any]) -> tuple[int, int]:
    rows = table.get("rows") or []
    row_count = table.get("row_count")
    col_count = table.get("column_count")
    if row_count is None:
        row_count = len(rows)
    if col_count is None:
        col_count = max((len(row) for row in rows), default=0)
    return int(row_count), int(col_count)


def _format_dims(row_count: int, col_count: int) -> str:
    return f"{row_count}×{col_count}"


def _build_raw_text(caption: str | None, rows: list[list[str]]) -> str:
    lines: list[str] = []
    if caption and caption.strip():
        lines.append(caption.strip())
    for row in rows:
        lines.append("\t".join(str(cell) for cell in row))
    return "\n".join(lines)


def _find_tables_container(root: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Return the mutable tables list inside common extraction output shapes."""
    if isinstance(root.get("tables"), list):
        return root["tables"]
    return None


def _apply_correction(table: dict[str, Any], correction: dict[str, Any]) -> dict[str, Any]:
    """Return old dimensions before mutation (for summary)."""
    old_dims = _dimensions(table)

    caption = correction.get("caption")
    headers = correction.get("headers") or []
    rows = correction.get("rows") or []

    table["caption"] = caption
    table["headers"] = headers
    table["rows"] = rows
    table["row_count"] = len(rows)
    table["column_count"] = max((len(row) for row in rows), default=0)
    table["raw_text"] = _build_raw_text(caption, rows)

    quality = table.get("extraction_quality")
    if not isinstance(quality, dict):
        quality = {}
        table["extraction_quality"] = quality
    quality["manually_corrected"] = True
    quality["status"] = "corrected"

    new_dims = _dimensions(table)
    return {"old": old_dims, "new": new_dims}


def _build_table_index(root: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    tables = _find_tables_container(root)
    if tables is None:
        return None
    by_id: dict[str, dict[str, Any]] = {}
    for table in tables:
        if not isinstance(table, dict):
            continue
        tid = _table_id(table)
        if tid:
            by_id[tid] = table
    return by_id


def _print_caption_fix_report(
    updated: list[str],
    skipped: list[str],
    missing: list[str],
    saved_path: str,
) -> None:
    print(f"Caption fixes saved to {saved_path}")
    if updated:
        print("Updated (was null/empty):")
        for tid in updated:
            print(f"  - {tid}")
    if skipped:
        print("Skipped (caption already set):")
        for tid in skipped:
            print(f"  - {tid}")
    if missing:
        print("WARNING: table_id not found in output:")
        for tid in missing:
            print(f"  - {tid}")


def main(argv: list[str]) -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    fix_captions, positional = _parse_argv(argv)

    output_path = (
        positional[0] if positional else os.path.join(script_dir, "output.json")
    )
    corrections_path = (
        positional[1]
        if len(positional) > 1
        else os.path.join(script_dir, "table_corrections.json")
    )
    fixed_path = (
        positional[2]
        if len(positional) > 2
        else os.path.join(script_dir, "output_fixed.json")
    )

    if not os.path.isfile(output_path):
        print(f"ERROR: output file not found: {output_path}", file=sys.stderr)
        return 1

    root = _load_json(output_path)
    by_id = _build_table_index(root)
    if by_id is None:
        print(
            "ERROR: could not find a top-level 'tables' array in output.json",
            file=sys.stderr,
        )
        return 1

    caption_only = fix_captions and len(positional) <= 1
    if caption_only:
        updated, skipped, missing = _apply_caption_only_fixes(by_id)
        _save_json(output_path, root)
        _print_caption_fix_report(updated, skipped, missing, output_path)
        return 0

    if not os.path.isfile(corrections_path):
        print(f"ERROR: corrections file not found: {corrections_path}", file=sys.stderr)
        return 1

    corrections = _load_json(corrections_path)
    if not isinstance(corrections, dict):
        print("ERROR: table_corrections.json must be a JSON object", file=sys.stderr)
        return 1

    summary_rows: list[tuple[str, str, str, str]] = []
    not_found: list[str] = []

    for tid, correction in corrections.items():
        if tid not in by_id:
            not_found.append(tid)
            continue
        dims = _apply_correction(by_id[tid], correction)
        summary_rows.append(
            (
                tid,
                _format_dims(*dims["old"]),
                _format_dims(*dims["new"]),
                "corrected",
            )
        )

    uncorrected: list[str] = []
    for tid in sorted(by_id):
        if tid not in corrections:
            uncorrected.append(tid)

    if fix_captions:
        updated, skipped, missing = _apply_caption_only_fixes(by_id)
        _save_json(output_path, root)
        _print_caption_fix_report(updated, skipped, missing, output_path)

    _save_json(fixed_path, root)

    print(f"Wrote {fixed_path}")
    print()
    print(f"{'table_id':<14} | {'old row×col':<12} | {'new row×col':<12} | status")
    print("-" * 60)
    for tid, old_d, new_d, status in summary_rows:
        print(f"{tid:<14} | {old_d:<12} | {new_d:<12} | {status}")

    if not_found:
        print()
        print("WARNING: correction table_id(s) not found in output.json:")
        for tid in not_found:
            print(f"  - {tid}")

    if uncorrected:
        print()
        print("WARNING: table(s) in output.json without entries in table_corrections.json:")
        for tid in uncorrected:
            t = by_id[tid]
            print(f"  - {tid} ({_format_dims(*_dimensions(t))})")

    print()
    print(
        f"Summary: {len(summary_rows)} corrected, "
        f"{len(not_found)} correction id(s) missing, "
        f"{len(uncorrected)} table(s) uncorrected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
