"""Tests for IEEE entity encoding in agent XML output."""

from app.utils.xml_helpers import (
    clean_extracted_abstract,
    encode_ieee_text_entities,
    post_process_ieee_entities,
)


def test_ligatures_expand_to_ascii_not_hex() -> None:
    assert encode_ieee_text_entities("total thea\ufb02avins") == "total theaflavins"
    assert encode_ieee_text_entities("speci\ufb01c") == "specific"
    assert "&#xFB" not in encode_ieee_text_entities("dif\ufb01culty and thea\ufb02avins")


def test_punctuation_uses_ieee_hex_entities() -> None:
    assert encode_ieee_text_entities("A\u2014B") == "A&#x2014;B"
    assert encode_ieee_text_entities("\u201cquoted\u201d") == "&#x201C;quoted&#x201D;"


def test_accented_letters_use_hex_entities() -> None:
    assert encode_ieee_text_entities("café") == "caf&#x00E9;"


def test_clean_extracted_abstract_strips_label_and_hyphenation() -> None:
    raw = "Abstract—In this facile approach, a well-developed voltam- metric tongue"
    assert clean_extracted_abstract(raw).startswith("In this facile")
    assert "voltammetric" in clean_extracted_abstract(raw)


def test_post_process_does_not_double_escape_hex_entities() -> None:
    xml = "<abstract><p>\u2014In this approach</p></abstract>"
    out = post_process_ieee_entities(xml)
    assert "&amp;#x2014;" not in out
    assert "&#x2014;" in out
