"""Tests for IEEE entity encoding in agent XML output."""

from app.utils.xml_helpers import (
    clean_extracted_abstract,
    collapse_ieee_empty_element_tags,
    encode_ieee_text_entities,
    expand_self_closing_empty_tags,
    finalize_ieee_xml,
    format_ieee_empty_element_tags,
    post_process_ieee_entities,
)


def test_ligatures_expand_to_ascii_not_hex() -> None:
    assert encode_ieee_text_entities("total thea\ufb02avins") == "total theaflavins"
    assert encode_ieee_text_entities("speci\ufb01c") == "specific"
    assert "&#xFB" not in encode_ieee_text_entities("dif\ufb01culty and thea\ufb02avins")


def test_punctuation_uses_ieee_hex_entities() -> None:
    assert encode_ieee_text_entities("A\u2014B") == "A&#x2014;B"
    assert encode_ieee_text_entities("\u201cquoted\u201d") == "&#x201C;quoted&#x201D;"
    assert encode_ieee_text_entities("\u2022") == "&#x2022;"


def test_post_process_encodes_bullet_label_and_lone_star_label() -> None:
    xml = "<list-item><label>\u2022</label></list-item>"
    out = post_process_ieee_entities(xml)
    assert "<label>&#x2022;</label>" in out
    out_star = post_process_ieee_entities("<label>*</label>")
    assert "<label>&#x002A;</label>" in out_star


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


def test_collapse_graphic_col_and_count_tags_to_self_closing() -> None:
    raw = (
        '<graphic xlink:href="li1.eps"></graphic>'
        '<col span="4"></col>'
        '<fig-count count="10"></fig-count>'
        "<xplore-article-id></xplore-article-id>"
    )
    out = format_ieee_empty_element_tags(raw)
    assert '<graphic xlink:href="li1.eps"/>' in out
    assert '<col span="4"/>' in out
    assert '<fig-count count="10"/>' in out
    assert "<xplore-article-id></xplore-article-id>" in out
    assert "<xplore-article-id/>" not in out


def test_expand_self_closing_empty_tags_to_explicit_pairs() -> None:
    raw = (
        "<article-meta>"
        "<xplore-article-id/>"
        "<xplore-issue/>"
        "<xplore-pub-id/>"
        '<assembly-group sequence="0"/>'
        "</article-meta>"
    )
    out = expand_self_closing_empty_tags(raw)
    assert "<xplore-article-id></xplore-article-id>" in out
    assert "<xplore-issue></xplore-issue>" in out
    assert "<xplore-pub-id></xplore-pub-id>" in out
    assert '<assembly-group sequence="0"></assembly-group>' in out
    assert "/>" not in out


def test_finalize_ieee_xml_encodes_front_matter_institutions() -> None:
    xml = (
        '<?xml version="1.0"?><article><front><article-meta>'
        "<aff><institution>Universit\xe9 de Lyon</institution></aff>"
        "</article-meta></front></article>"
    )
    out = finalize_ieee_xml(xml)
    assert "Universit&#x00E9;" in out
    assert "&amp;#x00E9;" not in out


def test_finalize_ieee_xml_repairs_double_escaped_entities() -> None:
    xml = (
        '<?xml version="1.0"?><article><front><article-meta>'
        "<institution>Universit&amp;#x00E1; di Verona</institution>"
        "</article-meta></front></article>"
    )
    out = finalize_ieee_xml(xml)
    assert "Universit&#x00E1;" in out
    assert "&amp;#x00E1;" not in out
