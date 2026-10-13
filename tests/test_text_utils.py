"""Tests for shared text normalization helpers."""

from __future__ import annotations

from app.utils.text_utils import (
    dehyphenate_line_breaks,
    infer_drop_cap_from_paragraph_start,
    infer_drop_cap_letter,
    merge_block_texts,
)


def test_dehyphenate_line_breaks_joins_split_words() -> None:
    assert dehyphenate_line_breaks("instrumen- tal means") == "instrumental means"
    assert dehyphenate_line_breaks("quality assess- ment of tea") == "quality assessment of tea"
    assert (
        dehyphenate_line_breaks(
            "myths surrounding political com-mitment and poetry"
        )
        == "myths surrounding political commitment and poetry"
    )
    assert dehyphenate_line_breaks("instrumen-tal means") == "instrumental means"


def test_dehyphenate_line_breaks_preserves_intentional_hyphens() -> None:
    assert dehyphenate_line_breaks("t-Distributed stochastic") == "t-Distributed stochastic"
    assert dehyphenate_line_breaks("self-aware poets") == "self-aware poets"
    assert dehyphenate_line_breaks("high-quality poetry") == "high-quality poetry"
    assert dehyphenate_line_breaks("anti-fascism and anti-imperialism") == (
        "anti-fascism and anti-imperialism"
    )


def test_dehyphenate_capitalized_line_breaks() -> None:
    assert dehyphenate_line_breaks("their Com-munist Party") == "their Communist Party"
    assert dehyphenate_line_breaks("the Span-ish Republic") == "the Spanish Republic"
    assert dehyphenate_line_breaks("Sec-ond, this book") == "Second, this book"


def test_merge_block_texts_joins_drop_cap_and_word() -> None:
    assert merge_block_texts(["R", "ESEARCHERS have been seeking"]) == "RESEARCHERS have been seeking"


def test_merge_block_texts_joins_line_break_hyphen_fragments() -> None:
    assert merge_block_texts(["instrumen-", "tal means"]) == "instrumental means"


def test_merge_block_texts_joins_wrapped_words_without_hyphen() -> None:
    assert merge_block_texts(["instru", "ments like electronic"]) == "instruments like electronic"
    assert merge_block_texts(["a sin", "gle sensor"]) == "a single sensor"
    assert merge_block_texts(["Jadavpur Univer", "sity [7]"]) == "Jadavpur University [7]"
    assert "occur as one" in merge_block_texts(
        ["Several stages occur as", "one transitions from the old"]
    )
    assert merge_block_texts(["give up after", "repeated encounters"]) == (
        "give up after repeated encounters"
    )


def test_infer_drop_cap_letter_for_researchers() -> None:
    assert infer_drop_cap_letter("ESEARCHERS have been seeking") == "R"


def test_infer_drop_cap_from_to_begin_merge() -> None:
    assert infer_drop_cap_from_paragraph_start("TO begin with a simple setting") == "T"
