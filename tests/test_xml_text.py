"""Tests for XML text sanitization."""

from __future__ import annotations

from lxml import etree

from app.utils.xml_text import (
    escape_xml_attribute,
    escape_xml_text,
    find_invalid_xml_char_codes,
    normalize_for_xml_serialization,
    normalize_person_name_text,
    normalize_typographic_ligatures,
    normalize_typographic_quotes,
    sanitize_xml_text,
    set_lxml_text,
    should_encode_as_hex_entity,
)


def test_sanitize_xml_text_removes_control_characters() -> None:
    assert sanitize_xml_text("a\x00b\x01c\x08d") == "abcd"
    assert sanitize_xml_text("a\x02b\x1fc") == "abc"
    assert sanitize_xml_text("keep\ttab\nand\rreturn") == "keep\ttab\nand\rreturn"


def test_sanitize_xml_text_preserves_unicode_and_emoji() -> None:
    """Sanitization keeps Unicode; final serialization encodes non-ASCII as entities."""
    assert sanitize_xml_text("μ alpha β") == "μ alpha β"
    assert sanitize_xml_text("hello 👋") == "hello 👋"


def test_find_invalid_xml_char_codes() -> None:
    assert find_invalid_xml_char_codes("a\x00b") == [0]
    assert find_invalid_xml_char_codes("a\x01b\x08c") == [1, 8]
    assert find_invalid_xml_char_codes("tab\there") == []
    assert find_invalid_xml_char_codes("line\nbreak") == []


def test_escape_xml_text_strips_and_escapes_core_entities_only() -> None:
    assert escape_xml_text("a\x02<b>") == "a&lt;b&gt;"
    assert escape_xml_text('say "hi"') == 'say "hi"'
    assert escape_xml_text("don't stop") == "don't stop"
    assert escape_xml_text("a & b") == "a &amp; b"


def test_normalize_typographic_quotes() -> None:
    assert normalize_typographic_quotes("it\u2019s a \u201ctest\u201d") == 'it\'s a "test"'


def test_normalize_typographic_ligatures() -> None:
    assert normalize_typographic_ligatures("dif\ufb01culty") == "difficulty"
    assert normalize_typographic_ligatures("af\ufb00licting") == "afflicting"


def test_should_encode_as_hex_entity_only_for_letters() -> None:
    assert should_encode_as_hex_entity("é") is True
    assert should_encode_as_hex_entity("f") is False
    assert should_encode_as_hex_entity("\ufb01") is False


def test_normalize_for_xml_serialization_expands_ligatures() -> None:
    assert normalize_for_xml_serialization("speci\ufb01c") == "specific"


def test_escape_xml_attribute_escapes_double_quotes_for_intermediate_output() -> None:
    assert escape_xml_attribute('value with "quotes"') == "value with &quot;quotes&quot;"
    assert escape_xml_attribute("value with 'apostrophe'") == "value with 'apostrophe'"


def test_set_lxml_text_accepts_sanitized_content() -> None:
    element = etree.Element("p")
    set_lxml_text(element, "safe\x00text\x08here")
    assert element.text == "safetexthere"
    etree.tostring(element, encoding="unicode")


def test_normalize_person_name_text_strips_surrounding_whitespace() -> None:
    assert normalize_person_name_text(" Madhurima ") == "Madhurima"
    assert normalize_person_name_text("\nMoulick\n") == "Moulick"
    assert normalize_person_name_text("\nMary\nJane\n") == "Mary Jane"
    assert normalize_person_name_text(None) == ""


def test_set_lxml_text_serializes_supplementary_unicode() -> None:
    element = etree.Element("p")
    set_lxml_text(element, "emoji 😀")
    xml = etree.tostring(element, encoding="unicode")
    assert "😀" in xml
