"""Tests for embedded Roman section heading detection and splitting."""

from __future__ import annotations

from app.services.layout.semantic_patterns import (
    author_running_header_prefix,
    extract_leading_roman_section_heading,
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
