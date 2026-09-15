"""Tests for XML text sanitization."""

from __future__ import annotations

from lxml import etree

from app.utils.xml_text import (
    escape_xml_text,
    find_invalid_xml_char_codes,
    sanitize_xml_text,
    set_lxml_text,
)


def test_sanitize_xml_text_removes_control_characters() -> None:
    assert sanitize_xml_text("a\x00b\x01c\x08d") == "abcd"
    assert sanitize_xml_text("a\x02b\x1fc") == "abc"
    assert sanitize_xml_text("keep\ttab\nand\rreturn") == "keep\ttab\nand\rreturn"


def test_sanitize_xml_text_preserves_unicode_and_emoji() -> None:
    assert sanitize_xml_text("μ alpha β") == "μ alpha β"
    assert sanitize_xml_text("hello 👋") == "hello 👋"


def test_find_invalid_xml_char_codes() -> None:
    assert find_invalid_xml_char_codes("a\x00b") == [0]
    assert find_invalid_xml_char_codes("a\x01b\x08c") == [1, 8]
    assert find_invalid_xml_char_codes("tab\there") == []
    assert find_invalid_xml_char_codes("line\nbreak") == []


def test_escape_xml_text_strips_and_escapes() -> None:
    assert escape_xml_text("a\x02<b>") == "a&lt;b&gt;"
    assert escape_xml_text('say "hi"') == "say &quot;hi&quot;"


def test_set_lxml_text_accepts_sanitized_content() -> None:
    element = etree.Element("p")
    set_lxml_text(element, "safe\x00text\x08here")
    assert element.text == "safetexthere"
    etree.tostring(element, encoding="unicode")


def test_set_lxml_text_serializes_supplementary_unicode() -> None:
    element = etree.Element("p")
    set_lxml_text(element, "emoji 😀")
    xml = etree.tostring(element, encoding="unicode")
    assert "😀" in xml
