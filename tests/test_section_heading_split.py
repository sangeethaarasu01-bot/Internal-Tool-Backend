"""Tests for embedded Roman section heading detection and splitting."""

from __future__ import annotations

from app.services.layout.semantic_patterns import (
    author_running_header_prefix,
    extract_leading_roman_section_heading,
    is_reference_like_heading,
    is_roman_section_heading,
    matches_author_running_header_prefix,
    order_authors_with_corresponding,
    parse_author_names,
    split_section_and_body,
    split_section_label_and_title,
)


def test_is_roman_section_heading_on_normalized_block_with_body() -> None:
    text = (
        "IV. CONCLUSION The current approach focuses on the development of an "
        "e-tongue comprising an array of highly specific MIP electrodes"
    )
    assert is_roman_section_heading(text) is True
    assert extract_leading_roman_section_heading(text) == "IV. CONCLUSION"


def test_split_section_and_body_on_normalized_text() -> None:
    text = "IV. CONCLUSION The current approach focuses on the development"
    heading, body = split_section_and_body(text)
    assert heading == "IV. CONCLUSION"
    assert body.startswith("The current approach")


def test_author_running_header_prefix_uses_up_to_five_chars() -> None:
    assert author_running_header_prefix("Moulick") == "MOULI"
    assert author_running_header_prefix("Roy") == "ROY"
    assert author_running_header_prefix("Das") == "DAS"


def test_matches_author_running_header_prefix_allows_longer_detected_token() -> None:
    assert matches_author_running_header_prefix("MOULICK", ["MOULI"]) is True


def test_order_authors_with_corresponding_moves_match_first() -> None:
    authors = ["Madhurima Moulick", "Sagar Chowdhury", "Runu Banerjee Roy"]
    ordered = order_authors_with_corresponding(authors, "Runu Banerjee Roy")
    assert ordered[0] == "Runu Banerjee Roy"
    assert ordered[1:] == ["Madhurima Moulick", "Sagar Chowdhury"]


def test_parse_author_names_splits_member_ieee_suffix() -> None:
    names = parse_author_names("Madhurima Moulick, Sagar Chowdhury, Member, IEEE, and Jeet Naskar")
    assert names == ["Madhurima Moulick", "Sagar Chowdhury", "Jeet Naskar"]


def test_split_section_label_and_title_for_roman_sections() -> None:
    assert split_section_label_and_title("I. INTRODUCTION") == ("I.", "INTRODUCTION")
    assert split_section_label_and_title("IV. CONCLUSION") == ("IV.", "CONCLUSION")


def test_split_section_label_and_title_for_letter_subsections() -> None:
    assert split_section_label_and_title("A. DPV Responses") == ("A.", "DPV Responses")


def test_reference_like_heading_rejects_bibliography_line() -> None:
    line = "W. L. Whittaker, \u2018\u2018Steering and control of a passively articulated robot,\u2019\u2019"
    assert is_reference_like_heading(line) is True
    assert is_reference_like_heading("A. CONVENTIONAL POWERTRAIN") is False


def test_embedded_letter_subsection_in_roman_block() -> None:
    from app.models.document_structure import ProcessedBlock
    from app.services.layout.document_pipeline import _build_structure, _parse_embedded_letter_subsection

    block = ProcessedBlock(
        block_id="p2_b7",
        page_number=2,
        reading_order_index=0,
        column="LEFT",
        classification="SECTION",
        confidence=0.9,
        exclude_from_content=False,
        exclusion_reason=None,
        bbox=[50.0, 40.0, 300.0, 80.0],
        text="II. PARALLEL-SERIES HYBRID SYSTEM\nA. CONVENTIONAL POWERTRAIN",
        block_type="text",
        dominant_font="Helvetica",
        dominant_font_size=10.0,
        is_bold=True,
    )
    heading, body, _ = _parse_embedded_letter_subsection(block.text, block)
    assert heading == "A. CONVENTIONAL POWERTRAIN"
    assert body is None
    sections, _, _, _ = _build_structure([block])
    headings = [section.heading for section in sections]
    assert "II. PARALLEL-SERIES HYBRID SYSTEM" in headings
    assert "A. CONVENTIONAL POWERTRAIN" in headings
