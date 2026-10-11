"""DocBook book body merge from PDF semantic IR."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.docbook_body_merge import apply_pdf_body_to_docbook_book
from app.services.extraction_workflow import ir_from_extraction_result
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.template_format import DOCBOOK_NS
from app.services.xml_output_router import generate_output_xml

ROOT = Path(__file__).resolve().parent.parent
DOCBOOK_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"
PASTORAL_LAYOUT = ROOT / "data" / "pipeline_debug" / "6acae32dbff2db96245fc3e5" / "layout_extraction.json"


def test_merge_replaces_template_chapter_paragraphs() -> None:
    tree = etree.parse(str(DOCBOOK_FIXTURE))
    root = tree.getroot()
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="heading",
                text="PDF Chapter",
                metadata={"level": 1},
                children=[
                    MappedSemanticNode(
                        semantic_type="paragraph",
                        text="Unique PDF paragraph marker xyzzy-12345.",
                    )
                ],
            )
        ],
        back={},
    )
    result = apply_pdf_body_to_docbook_book(root, mapping)
    assert result.applied
    xml = etree.tostring(root, encoding="unicode")
    assert "Body paragraph." not in xml
    assert "xyzzy-12345" in xml
    assert "PDF Chapter" in xml


@pytest.mark.skipif(not PASTORAL_LAYOUT.is_file(), reason="Pastoral layout fixture missing")
def test_pastoral_ir_replaces_marshall_template_narrative() -> None:
    layout = json.loads(PASTORAL_LAYOUT.read_text(encoding="utf-8"))
    ir = ir_from_extraction_result(layout)
    mapping = ir_to_semantic_mapping(ir)
    assert mapping.body

    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    xml, fmt, docbook_result = generate_output_xml(
        DOCBOOK_FIXTURE,
        schema,
        mapping,
        output_format="docbook_5",
        ir=ir,
    )
    assert fmt == "docbook_5"
    assert docbook_result is not None and docbook_result.body.applied
    assert "Body paragraph." not in xml
    assert "lived religion" in xml.lower() or "pastoral" in xml.lower()
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == f"{{{DOCBOOK_NS}}}book"
