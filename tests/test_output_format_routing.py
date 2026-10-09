"""Output-format routing for JATS vs DocBook generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from app.models.semantic_mapping import SemanticMappingBody
from app.services.output_format import (
    OUTPUT_DOCBOOK_5,
    OUTPUT_EPUB_3,
    OUTPUT_IEEE_JATS,
    OutputFormatError,
    resolve_output_format,
    template_format_from_schema,
)
from app.services.template_format import DOCBOOK_NS
from app.services.xml_generator import XmlGenerationError, generate_jats_xml
from app.services.xml_output_router import generate_output_xml

ROOT = Path(__file__).resolve().parent.parent
DOCBOOK_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"
JATS_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_template.xml"


def test_template_format_detection_docbook() -> None:
    schema = {"root_tag": "book", "template_format": "docbook_5_book"}
    assert template_format_from_schema(schema) == "docbook_5_book"
    assert resolve_output_format("auto", schema) == OUTPUT_DOCBOOK_5


def test_template_format_detection_article() -> None:
    schema = {"root_tag": "article", "template_format": "ieee_jats_article"}
    assert resolve_output_format("auto", schema) == OUTPUT_IEEE_JATS


def test_docbook_auto_routes_to_docbook_generator() -> None:
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt = generate_output_xml(
        DOCBOOK_FIXTURE,
        schema,
        mapping,
        output_format="auto",
    )
    assert fmt == OUTPUT_DOCBOOK_5
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == f"{{{DOCBOOK_NS}}}book"
    assert root.get("version") == "5.0"


def test_docbook_explicit_output_does_not_invoke_jats() -> None:
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt = generate_output_xml(
        DOCBOOK_FIXTURE,
        schema,
        mapping,
        output_format=OUTPUT_DOCBOOK_5,
    )
    assert fmt == OUTPUT_DOCBOOK_5
    assert DOCBOOK_NS in xml
    assert "Chapter One" in xml


def test_docbook_template_with_jats_output_rejected() -> None:
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    with pytest.raises(OutputFormatError, match="Cannot generate IEEE JATS"):
        resolve_output_format(OUTPUT_IEEE_JATS, schema)


def test_jats_generator_still_rejects_docbook_template_directly() -> None:
    mapping = SemanticMappingBody(front={}, body=[], back={})
    with pytest.raises(XmlGenerationError, match="got <book>"):
        generate_jats_xml(DOCBOOK_FIXTURE, mapping)


def test_stale_empty_schema_auto_uses_book_file_not_jats() -> None:
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt = generate_output_xml(
        DOCBOOK_FIXTURE,
        {},
        mapping,
        output_format="auto",
    )
    assert fmt == OUTPUT_DOCBOOK_5


def test_article_template_routes_to_jats() -> None:
    schema = {"template_format": "ieee_jats_article", "root_tag": "article"}
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt = generate_output_xml(
        JATS_FIXTURE,
        schema,
        mapping,
        output_format="auto",
    )
    assert fmt == OUTPUT_IEEE_JATS
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.tag == "article"


def test_epub_not_implemented() -> None:
    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    with pytest.raises(OutputFormatError, match="not implemented"):
        resolve_output_format(OUTPUT_EPUB_3, schema)
