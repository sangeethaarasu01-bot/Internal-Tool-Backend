"""Guards and routing for /generate-xml (book vs article, size limits)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.semantic_mapping import SemanticMappingBody
from app.services.generate_xml_guards import (
    JatsArticleRequiredError,
    JatsTransformTooLargeError,
    assert_jats_article_template_root,
    assert_jats_transform_payload_under_limit,
    effective_template_format,
    jats_requires_article_detail,
)
from app.services.output_format import OUTPUT_DOCBOOK_5, OUTPUT_IEEE_JATS, resolve_output_format
from app.services.xml_generator import XmlGenerationError, generate_jats_xml
from app.services.xml_output_router import generate_output_xml

ROOT = Path(__file__).resolve().parent.parent
DOCBOOK_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"
JATS_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_template.xml"


def test_empty_schema_routes_book_file_to_docbook_auto() -> None:
    assert (
        resolve_output_format("auto", {}, template_path=DOCBOOK_FIXTURE)
        == OUTPUT_DOCBOOK_5
    )
    assert effective_template_format({}, DOCBOOK_FIXTURE) == "docbook_5_book"


def test_empty_schema_book_file_does_not_invoke_jats_generator() -> None:
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml, fmt, _overlay = generate_output_xml(
        DOCBOOK_FIXTURE,
        {},
        mapping,
        output_format="auto",
    )
    assert fmt == OUTPUT_DOCBOOK_5
    assert "Chapter One" in xml


def test_jats_guard_message_for_book_template() -> None:
    with pytest.raises(JatsArticleRequiredError, match="got <book>"):
        assert_jats_article_template_root(DOCBOOK_FIXTURE)
    assert "book-compatible output" in jats_requires_article_detail("book")


def test_jats_generator_raises_friendly_422_message() -> None:
    mapping = SemanticMappingBody(front={}, body=[], back={})
    with pytest.raises(XmlGenerationError, match="got <book>"):
        generate_jats_xml(DOCBOOK_FIXTURE, mapping)


def test_jats_payload_size_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JATS_MAX_TRANSFORM_BYTES", "50")
    mapping = SemanticMappingBody(front={}, body=[], back={})
    with pytest.raises(JatsTransformTooLargeError, match="Chunk by <chapter>"):
        assert_jats_transform_payload_under_limit(JATS_FIXTURE, mapping)


def test_article_schema_still_routes_to_jats() -> None:
    schema = {"template_format": "ieee_jats_article", "root_tag": "article"}
    assert (
        resolve_output_format("auto", schema, template_path=JATS_FIXTURE)
        == OUTPUT_IEEE_JATS
    )
