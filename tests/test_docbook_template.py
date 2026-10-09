"""DocBook 5.0 book template acceptance, parsing, and JATS separation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from app.models.semantic_mapping import SemanticMappingBody
from app.services.docbook_template import parse_docbook_template_file
from app.services.extraction_workflow import ExtractionWorkflowError, parse_template_xml
from app.services.template_format import (
    DOCBOOK_NS,
    UnsupportedTemplateRootError,
    classify_template_root,
)
from app.services.template_parser import TemplateParser
from app.services.output_format import OUTPUT_DOCBOOK_5, OUTPUT_IEEE_JATS, OutputFormatError, resolve_output_format
from app.services.xml_generator import XmlGenerationError, generate_jats_xml
from app.services.xml_output_router import generate_output_xml
from app.models.semantic_mapping import SemanticMappingBody
from app.utils.xml_serializer import serialize_lxml_tree

ROOT = Path(__file__).resolve().parent.parent
DOCBOOK_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"
JATS_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_template.xml"
KNOWN_TAGS = ROOT / "app" / "constants" / "jats_2_0_known_tags.json"
INTEGRATION_BOOK = ROOT / "data" / "outputs" / "d459ad96-bf30-41a4-98ab-04c08d4f8b27.xml"


def test_docbook_book_root_accepted() -> None:
    tree = etree.parse(str(DOCBOOK_FIXTURE))
    root = tree.getroot()
    info = classify_template_root(root)
    assert info.local_name == "book"
    assert info.namespace_uri == DOCBOOK_NS
    assert info.version == "5.0"
    assert info.template_format == "docbook_5_book"


def test_docbook_nested_structure_preserved() -> None:
    parsed = parse_docbook_template_file(DOCBOOK_FIXTURE)
    tags = {node.tag for node in parsed.structure.children}
    assert "info" in tags
    assert "part" in tags
    assert "chapter" in tags

    chapter = next(node for node in parsed.structure.children if node.tag == "chapter")
    child_tags = {node.tag for node in chapter.children}
    assert "section" in child_tags
    assert "sidebar" in child_tags

    bib_section = next(
        node
        for node in chapter.children
        if node.tag == "section" and node.attributes.get("role") == "bibliography"
    )
    assert any(child.tag == "bibliolist" for child in bib_section.children)


def test_docbook_namespace_preserved_on_serialize() -> None:
    tree = etree.parse(str(DOCBOOK_FIXTURE))
    xml = serialize_lxml_tree(
        tree.getroot(),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )
    assert DOCBOOK_NS in xml
    assert 'version="5.0"' in xml


def test_docbook_metadata_from_info() -> None:
    parsed = parse_docbook_template_file(DOCBOOK_FIXTURE)
    meta = parsed.metadata
    assert meta.title == "Test Book"
    assert meta.subtitle == "Test Subtitle"
    assert meta.authors == ["Ada Lovelace", "Grace Hopper"]
    assert meta.publisher == "Test Publisher"
    assert meta.copyright_year == "2025"
    assert meta.copyright_holder == "Test Holder"
    assert meta.doi == "10.0000/testbook"
    assert len(meta.isbns) == 1
    assert meta.isbns[0].value == "978-0-000-00000-0"


def test_jats_article_template_still_valid() -> None:
    schema = parse_template_xml(JATS_FIXTURE)
    assert schema["root_tag"] == "article"
    assert schema["template_format"] == "ieee_jats_article"


def test_invalid_root_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<html><body/></html>", encoding="utf-8")
    with pytest.raises(ExtractionWorkflowError, match="Unsupported template root"):
        parse_template_xml(bad)


def test_jats_generation_rejects_docbook_template() -> None:
    mapping = SemanticMappingBody(front={}, body=[], back={})
    with pytest.raises(XmlGenerationError, match="got <book>"):
        generate_jats_xml(DOCBOOK_FIXTURE, mapping)


def test_router_auto_selects_docbook_for_book_template() -> None:
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    assert resolve_output_format("auto", schema) == OUTPUT_DOCBOOK_5
    xml, fmt = generate_output_xml(DOCBOOK_FIXTURE, schema, mapping, output_format="auto")
    assert fmt == OUTPUT_DOCBOOK_5
    assert "Test Book" in xml


def test_router_rejects_jats_output_for_docbook_template() -> None:
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    with pytest.raises(OutputFormatError, match="Cannot generate IEEE JATS"):
        resolve_output_format(OUTPUT_IEEE_JATS, schema)


def test_template_parser_docbook_schema_fields() -> None:
    schema = TemplateParser(DOCBOOK_FIXTURE, known_tags_path=KNOWN_TAGS).parse()
    assert schema.root_tag == "book"
    assert schema.template_format == "docbook_5_book"
    assert schema.root_namespace == DOCBOOK_NS
    assert schema.docbook_metadata is not None
    assert schema.docbook_metadata.title == "Test Book"


@pytest.mark.skipif(not INTEGRATION_BOOK.is_file(), reason="integration book XML not in workspace")
def test_integration_book_metadata() -> None:
    parsed = parse_docbook_template_file(INTEGRATION_BOOK)
    assert parsed.metadata.title == "Museum Flack"
    assert parsed.metadata.doi == "10.5040/9798216447917"
    assert parsed.metadata.publisher is not None
