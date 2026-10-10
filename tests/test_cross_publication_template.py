"""PDF + sample XML from different publications: structure reuse, PDF metadata in output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from app.services.docbook_template import extract_docbook_book_metadata
from app.services.identity_gates import (
    IdentityMismatchError,
    verify_post_generation_identity,
    verify_pre_generation_identity,
)
from app.services.output_format import OUTPUT_DOCBOOK_5
from app.services.source_identity import build_source_identity_from_extraction_doc
from app.services.template_format import DOCBOOK_NS
from app.services.xml_output_router import generate_output_xml
from app.models.semantic_mapping import SemanticMappingBody

ROOT = Path(__file__).resolve().parent.parent
PASTORAL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d8accac519efa424bcf8" / "phase1_document.json"
MARSHALL_PHASE1 = ROOT / "data" / "pipeline_debug" / "6ac8d119cac519efa424bcf5" / "phase1_document.json"
MARSHALL_BOOK_XML = (
    ROOT / "data" / "outputs" / "book_exports" / "6ac8dfef308ea3940d0a59f7" / "book.xml"
)
DOCBOOK_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"
JATS_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_template.xml"


def _extraction_doc(phase1_path: Path, extraction_id: str) -> dict:
    phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))
    return {
        "_id": extraction_id,
        "original_filename": phase1.get("source_filename"),
        "source_pdf_sha256": f"sha-{extraction_id}",
        "phase1": phase1,
        "page_count": len(phase1.get("pages") or []),
    }


@pytest.mark.skipif(
    not (PASTORAL_PHASE1.is_file() and MARSHALL_BOOK_XML.is_file()),
    reason="Pastoral / Marshall fixtures missing",
)
def test_pastoral_pdf_with_marshall_sample_xml_accepted_at_upload_gate() -> None:
    source = build_source_identity_from_extraction_doc(_extraction_doc(PASTORAL_PHASE1, "job-p"))
    template = {
        "template_schema": {"template_format": "docbook_5_book", "root_tag": "book"},
        "original_filename": "marshall.xml",
    }
    verify_pre_generation_identity(
        extraction_id="job-p",
        source=source,
        template=template,
        template_path=str(MARSHALL_BOOK_XML),
        output_format=OUTPUT_DOCBOOK_5,
    )


@pytest.mark.skipif(
    not (PASTORAL_PHASE1.is_file() and MARSHALL_BOOK_XML.is_file()),
    reason="Pastoral / Marshall fixtures missing",
)
def test_pastoral_pdf_marshall_template_output_metadata_from_pdf() -> None:
    source = build_source_identity_from_extraction_doc(_extraction_doc(PASTORAL_PHASE1, "job-pastoral"))
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt, overlay = generate_output_xml(
        MARSHALL_BOOK_XML,
        schema,
        mapping,
        output_format=OUTPUT_DOCBOOK_5,
        source=source,
    )
    assert fmt == OUTPUT_DOCBOOK_5
    assert overlay is not None and overlay.applied

    root = etree.fromstring(xml.encode("utf-8"))
    meta = extract_docbook_book_metadata(root)
    phase1 = json.loads(PASTORAL_PHASE1.read_text(encoding="utf-8"))

    assert "Pastoral Bearings" in (meta.title or "")
    assert meta.title != "Overcoming Student Apathy"
    assert any("9780739123607" in v.replace("-", "") for v in [i.value for i in meta.isbns])
    assert meta.copyright_year == "2010" or str(phase1["publication_year"]) in (meta.copyright_year or "")
    assert "6520177" not in (meta.doi or "")

    verify_post_generation_identity(
        extraction_id="job-pastoral",
        source=source,
        xml_content=xml,
        output_format=OUTPUT_DOCBOOK_5,
        expected_root="book",
    )

    assert "Overcoming Student Apathy" not in (meta.title or "")
    assert root.tag == f"{{{DOCBOOK_NS}}}book"


@pytest.mark.skipif(not MARSHALL_PHASE1.is_file(), reason="Marshall fixture missing")
def test_marshall_pdf_with_own_template_still_passes() -> None:
    if not MARSHALL_BOOK_XML.is_file():
        pytest.skip("Marshall book XML missing")
    source = build_source_identity_from_extraction_doc(_extraction_doc(MARSHALL_PHASE1, "job-m"))
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, _, _ = generate_output_xml(
        MARSHALL_BOOK_XML,
        schema,
        mapping,
        output_format=OUTPUT_DOCBOOK_5,
        source=source,
    )
    root = etree.fromstring(xml.encode("utf-8"))
    meta = extract_docbook_book_metadata(root)
    assert "Overcoming Student Apathy" in (meta.title or "") or "Student Apathy" in (meta.title or "")


def test_minimal_docbook_same_publication_overlay() -> None:
    source = build_source_identity_from_extraction_doc(
        {
            "_id": "job-local",
            "phase1": {
                "title": "Test Book",
                "isbn": "978-0-000-00000-0",
                "publication_year": 2025,
                "authors": ["Ada Lovelace"],
            },
            "source_pdf_sha256": "sha",
        }
    )
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt, _ = generate_output_xml(
        DOCBOOK_FIXTURE,
        schema,
        mapping,
        output_format="auto",
        source=source,
    )
    assert fmt == OUTPUT_DOCBOOK_5
    assert "Chapter One" in xml
    verify_post_generation_identity(
        extraction_id="job-local",
        source=source,
        xml_content=xml,
        output_format=OUTPUT_DOCBOOK_5,
        expected_root="book",
    )


def test_sequential_jobs_do_not_share_state() -> None:
    if not PASTORAL_PHASE1.is_file() or not MARSHALL_PHASE1.is_file():
        pytest.skip("fixtures missing")
    mapping = SemanticMappingBody(front={}, body=[], back={})
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    pastoral = build_source_identity_from_extraction_doc(_extraction_doc(PASTORAL_PHASE1, "seq-a"))
    marshall = build_source_identity_from_extraction_doc(_extraction_doc(MARSHALL_PHASE1, "seq-b"))
    xml_a, _, _ = generate_output_xml(
        DOCBOOK_FIXTURE, schema, mapping, source=pastoral, output_format="auto"
    )
    xml_b, _, _ = generate_output_xml(
        DOCBOOK_FIXTURE, schema, mapping, source=marshall, output_format="auto"
    )
    assert "Pastoral Bearings" in xml_a
    assert "Pastoral Bearings" not in xml_b


def test_sparse_pdf_metadata_warns_without_fabricating_title() -> None:
    source = build_source_identity_from_extraction_doc(
        {"_id": "sparse", "phase1": {}, "source_pdf_sha256": "sha"},
    )
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, _, overlay = generate_output_xml(
        DOCBOOK_FIXTURE,
        schema,
        mapping,
        source=source,
        output_format="auto",
    )
    assert overlay is not None
    assert overlay.warnings
    meta = extract_docbook_book_metadata(etree.fromstring(xml.encode("utf-8")))
    assert meta.title == "Test Book"


def test_invalid_xml_template_raises() -> None:
    import tempfile

    bad = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
    bad.write("<book><unclosed>")
    bad.close()
    mapping = SemanticMappingBody(front={}, body=[], back={})
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    try:
        with pytest.raises(etree.XMLSyntaxError):
            generate_output_xml(
                bad.name,
                schema,
                mapping,
                output_format=OUTPUT_DOCBOOK_5,
            )
    finally:
        Path(bad.name).unlink(missing_ok=True)


def test_jats_article_fixture_still_generates() -> None:
    source = build_source_identity_from_extraction_doc(
        {
            "_id": "jats-job",
            "phase1": {"title": "Sample Article"},
            "source_pdf_sha256": "sha",
            "result": {"structure": {"semantic": {"front": {}, "body": {}, "back": {}}}},
        }
    )
    schema = {"template_format": "ieee_jats_article", "root_tag": "article"}
    mapping = SemanticMappingBody(front={"title": "Sample Article"}, body=[], back={})
    xml, fmt, overlay = generate_output_xml(
        JATS_FIXTURE,
        schema,
        mapping,
        output_format="auto",
        source=source,
    )
    assert fmt == "ieee_jats"
    assert overlay is None
    assert "<article" in xml
