"""Integration tests for table extraction on the Kakichi reference PDF."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.pipeline.table_extraction.pipeline import run_extraction
from app.pipeline.table_extraction.validate import cell_empty_ratio

KAKICHI_PDF = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "pipeline_debug"
    / "access-kakichi-3657695-proof.pdf1"
    / "original.pdf"
)

TABLE_CAPTION_RE = re.compile(r"^TABLE\s+[IVX0-9]+", re.IGNORECASE)


@pytest.mark.skipif(not KAKICHI_PDF.is_file(), reason="Reference PDF not present locally")
def test_kakichi_table_extraction_quality() -> None:
    data = run_extraction(KAKICHI_PDF)
    tables = data.get("tables") or []

    assert data["table_count"] == len(tables)
    assert data["table_count"] >= 1
    assert data["table_count"] <= 8
    per_page = {
        row["page_number"]: row.get("emitted", 0)
        for row in (data.get("extraction_summary") or {}).get("per_page") or []
    }
    expected = {4: 1, 9: 1, 11: 2, 13: 2, 14: 2}
    for page_no, want in expected.items():
        assert per_page.get(page_no) == want, (
            f"page {page_no}: expected {want} tables, got {per_page.get(page_no)}"
        )
    assert data["table_count"] == sum(expected.values())

    table_1 = next((t for t in tables if (t.get("caption") or "").startswith("TABLE 1")), None)
    if table_1 is not None:
        blob = " ".join(
            str(c)
            for row in (table_1.get("headers") or []) + (table_1.get("rows") or [])
            for c in row
        ).casefold()
        assert "engine" in blob or "diesel" in blob

    for tbl in tables:
        for row in tbl.get("rows") or []:
            for cell in row:
                assert str(cell).lower() != "none"
        caption = (tbl.get("caption") or "").strip()
        if caption:
            assert TABLE_CAPTION_RE.match(caption.splitlines()[0])
        assert tbl.get("row_count", 0) <= 35
        headers = tbl.get("headers") or []
        body = tbl.get("rows") or []
        all_rows = ([headers] + body) if headers else body
        if not all_rows:
            continue
        if not any(str(c or "").strip() for row in all_rows for c in row):
            continue
        status = (tbl.get("extraction_quality") or {}).get("status", "")
        max_empty = 0.92 if status == "partial" else 0.85
        assert cell_empty_ratio(all_rows) <= max_empty
