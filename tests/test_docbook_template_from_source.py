"""Template generated from extraction metadata matches the source PDF."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from app.services.docbook_template_from_source import build_docbook_template_xml_from_phase1
from app.services.docbook_template import parse_docbook_template_file
from app.services.source_identity import build_source_identity_from_extraction_doc, build_template_identity
from app.services.source_identity import compare_source_to_template
from app.services.template_format import DOCBOOK_NS

ROOT = Path(__file__).resolve().parent.parent
PASTORAL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d8accac519efa424bcf8" / "phase1_document.json"
MARSHALL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d119cac519efa424bcf5" / "phase1_document.json"


@pytest.mark.skipif(not PASTORAL_PHASE1.is_file(), reason="fixture missing")
def test_from_source_pastoral_metadata_no_foreign_doi() -> None:
    phase1 = json.loads(PASTORAL_PHASE1.read_text(encoding="utf-8"))
    xml = build_docbook_template_xml_from_phase1(phase1)
    assert "6520177" not in xml
    assert "Pastoral Bearings" in xml
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == f"{{{DOCBOOK_NS}}}book"
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as tmp:
        tmp.write(xml)
        tmp_path = tmp.name
    try:
        meta = parse_docbook_template_file(tmp_path).metadata
        assert meta.doi is None or "6520177" not in (meta.doi or "")
        source = build_source_identity_from_extraction_doc(
            {
                "_id": "job-pastoral",
                "phase1": phase1,
                "source_pdf_sha256": "sha",
                "original_filename": phase1.get("source_filename"),
            }
        )
        template_id = build_template_identity(
            {"template_schema": {"template_format": "docbook_5_book"}, "original_filename": "t.xml"},
            tmp_path,
        )
        assert not compare_source_to_template(source, template_id)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@pytest.mark.skipif(not MARSHALL_PHASE1.is_file(), reason="fixture missing")
def test_from_source_marshall_matches_marshall_phase1() -> None:
    phase1 = json.loads(MARSHALL_PHASE1.read_text(encoding="utf-8"))
    xml = build_docbook_template_xml_from_phase1(phase1)
    assert "Overcoming Student Apathy" in xml
    assert "6520177" not in xml or "9798216520177" not in xml
