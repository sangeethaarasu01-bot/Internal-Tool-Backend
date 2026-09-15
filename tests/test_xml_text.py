"""Tests for XML text sanitization."""

from app.utils.xml_text import escape_xml_text, sanitize_xml_text


def test_sanitize_xml_text_removes_control_characters() -> None:
    assert sanitize_xml_text("a\x02b\x1fc") == "abc"
    assert sanitize_xml_text("keep\ttab\nand\rreturn") == "keep\ttab\nand\rreturn"


def test_escape_xml_text_strips_and_escapes() -> None:
    assert escape_xml_text("a\x02<b>") == "a&lt;b&gt;"
    assert escape_xml_text('say "hi"') == "say &quot;hi&quot;"
