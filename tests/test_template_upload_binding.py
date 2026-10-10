"""Template must bind to the current extraction's source PDF — not a prior session."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent
PASTORAL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d8accac519efa424bcf8" / "phase1_document.json"
MARSHALL_BOOK_XML = (
    ROOT / "data" / "outputs" / "book_exports" / "6ac8dfef308ea3940d0a59f7" / "book.xml"
)

client = TestClient(app)
EXTRACTION_ID = "507f1f77bcf86cd799439011"


def _pastoral_doc() -> dict:
    phase1 = json.loads(PASTORAL_PHASE1.read_text(encoding="utf-8"))
    return {
        "_id": EXTRACTION_ID,
        "status": "completed",
        "original_filename": phase1.get("source_filename"),
        "source_pdf_sha256": "abc-pastoral-sha256",
        "phase1": phase1,
        "page_count": len(phase1.get("pages") or []),
        "result": {"structure": {"semantic": {"front": {}, "body": {}, "back": {}}}},
        "template": None,
    }


@pytest.mark.skipif(
    not (PASTORAL_PHASE1.is_file() and MARSHALL_BOOK_XML.is_file()),
    reason="fixtures missing",
)
def test_template_upload_accepts_cross_publication_sample_xml(tmp_path: Path) -> None:
    doc = _pastoral_doc()
    col = MagicMock()
    col.find_one.return_value = doc
    col.update_one.return_value = MagicMock(modified_count=1)

    with patch("app.routes.extractions.extractions_col", return_value=col):
        with patch("app.routes.extractions.template_storage_dir", return_value=tmp_path):
            with patch("app.routes.extractions._oid", return_value=EXTRACTION_ID):
                xml_bytes = MARSHALL_BOOK_XML.read_bytes()
                res = client.post(
                    f"/api/extractions/{EXTRACTION_ID}/template",
                    files={"file": ("marshall.xml", BytesIO(xml_bytes), "application/xml")},
                )
    assert res.status_code == 200
    col.update_one.assert_called_once()


@pytest.mark.skipif(
    not (PASTORAL_PHASE1.is_file() and MARSHALL_BOOK_XML.is_file()),
    reason="fixtures missing",
)
def test_template_upload_accepts_minimal_docbook_for_pastoral(tmp_path: Path) -> None:
    doc = _pastoral_doc()
    col = MagicMock()
    col.find_one.return_value = doc
    col.update_one.return_value = MagicMock(modified_count=1)
    pastoral_template = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"
    if not pastoral_template.is_file():
        pytest.skip("no minimal docbook fixture")

    with patch("app.routes.extractions.extractions_col", return_value=col):
        with patch("app.routes.extractions.template_storage_dir", return_value=tmp_path):
            with patch("app.routes.extractions._oid", return_value=EXTRACTION_ID):
                res = client.post(
                    f"/api/extractions/{EXTRACTION_ID}/template",
                    files={
                        "file": (
                            "sample.xml",
                            BytesIO(pastoral_template.read_bytes()),
                            "application/xml",
                        )
                    },
                )
    assert res.status_code == 200
