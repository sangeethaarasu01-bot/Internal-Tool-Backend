"""Regression: one upload cannot receive another document's template metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.identity_gates import IdentityMismatchError, verify_pre_generation_identity
from app.services.output_naming import safe_output_xml_filename
from app.services.source_identity import (
    build_source_identity_from_extraction_doc,
    compare_source_to_template,
    title_overlap_score,
)
from app.services.source_identity import build_template_identity

ROOT = Path(__file__).resolve().parent.parent
PASTORAL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d8accac519efa424bcf8" / "phase1_document.json"
MARSHALL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d119cac519efa424bcf5" / "phase1_document.json"
MARSHALL_DOCBOOK = (
    ROOT / "data" / "outputs" / "book_exports" / "6ac8dfef308ea3940d0a59f7" / "book.xml"
)
WRONG_DOCBOOK = ROOT / "data" / "outputs" / "d459ad96-bf30-41a4-98ab-04c08d4f8b27.xml"


def _extraction_doc(phase1_path: Path, extraction_id: str) -> dict:
    phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))
    return {
        "_id": extraction_id,
        "original_filename": phase1.get("source_filename"),
        "source_pdf_sha256": f"sha-{extraction_id}",
        "phase1": phase1,
        "page_count": len(phase1.get("pages") or []),
    }


@pytest.mark.skipif(not PASTORAL_PHASE1.is_file(), reason="Pastoral fixture missing")
def test_pastoral_and_marshall_titles_do_not_overlap() -> None:
    pastoral = json.loads(PASTORAL_PHASE1.read_text(encoding="utf-8"))
    marshall = json.loads(MARSHALL_PHASE1.read_text(encoding="utf-8"))
    assert title_overlap_score(pastoral["title"], marshall["title"]) < 0.35


@pytest.mark.skipif(
    not (PASTORAL_PHASE1.is_file() and WRONG_DOCBOOK.is_file()),
    reason="Book fixtures missing",
)
def test_pre_generation_gate_rejects_pastoral_pdf_with_marshall_template() -> None:
    doc = _extraction_doc(PASTORAL_PHASE1, "job-pastoral-001")
    source = build_source_identity_from_extraction_doc(doc)
    template = {
        "template_id": "tpl-marshall",
        "original_filename": "marshall_book.xml",
        "file_path": str(WRONG_DOCBOOK),
        "template_schema": {"template_format": "docbook_5_book", "root_tag": "book"},
    }
    with pytest.raises(IdentityMismatchError, match="do not match"):
        verify_pre_generation_identity(
            extraction_id="job-pastoral-001",
            source=source,
            template=template,
            template_path=str(WRONG_DOCBOOK),
            output_format="docbook_5",
        )


@pytest.mark.skipif(
    not (MARSHALL_PHASE1.is_file() and MARSHALL_DOCBOOK.is_file()),
    reason="Marshall fixtures missing",
)
def test_marshall_pdf_with_marshall_template_passes_pre_gate() -> None:
    doc = _extraction_doc(MARSHALL_PHASE1, "job-marshall-001")
    source = build_source_identity_from_extraction_doc(doc)
    template = {
        "template_id": "tpl-marshall",
        "original_filename": "marshall_book.xml",
        "file_path": str(MARSHALL_DOCBOOK),
        "template_schema": {"template_format": "docbook_5_book", "root_tag": "book"},
    }
    verify_pre_generation_identity(
        extraction_id="job-marshall-001",
        source=source,
        template=template,
        template_path=str(MARSHALL_DOCBOOK),
        output_format="docbook_5",
    )


def test_output_filename_uses_job_not_doi() -> None:
    name = safe_output_xml_filename(
        extraction_id="507f1f77bcf86cd799439011",
        original_pdf_filename="9798216211563_web.pdf",
    )
    assert "6520177" not in name
    assert "9798216211563" in name
    assert "507f1f77bcf8" in name


@pytest.mark.skipif(not PASTORAL_PHASE1.is_file(), reason="Pastoral fixture missing")
def test_sequential_identity_records_differ() -> None:
    pastoral = build_source_identity_from_extraction_doc(
        _extraction_doc(PASTORAL_PHASE1, "job-a"),
    )
    marshall = build_source_identity_from_extraction_doc(
        _extraction_doc(MARSHALL_PHASE1, "job-b"),
    )
    assert pastoral.extraction_id != marshall.extraction_id
    assert pastoral.source_pdf_sha256 != marshall.source_pdf_sha256
    assert pastoral.title != marshall.title
