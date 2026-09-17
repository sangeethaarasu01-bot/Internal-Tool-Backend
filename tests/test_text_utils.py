"""Tests for shared text normalization helpers."""

from __future__ import annotations

from app.utils.text_utils import dehyphenate_line_breaks, infer_drop_cap_letter, merge_block_texts


def test_dehyphenate_line_breaks_joins_split_words() -> None:
    assert dehyphenate_line_breaks("instrumen- tal means") == "instrumental means"
    assert dehyphenate_line_breaks("quality assess- ment of tea") == "quality assessment of tea"


def test_dehyphenate_line_breaks_preserves_intentional_hyphens() -> None:
    assert dehyphenate_line_breaks("t-Distributed stochastic") == "t-Distributed stochastic"


def test_merge_block_texts_joins_drop_cap_and_word() -> None:
    assert merge_block_texts(["R", "ESEARCHERS have been seeking"]) == "RESEARCHERS have been seeking"


def test_merge_block_texts_joins_line_break_hyphen_fragments() -> None:
    assert merge_block_texts(["instrumen-", "tal means"]) == "instrumental means"


def test_merge_block_texts_joins_wrapped_words_without_hyphen() -> None:
    assert merge_block_texts(["instru", "ments like electronic"]) == "instruments like electronic"
    assert merge_block_texts(["a sin", "gle sensor"]) == "a single sensor"
    assert merge_block_texts(["Jadavpur Univer", "sity [7]"]) == "Jadavpur University [7]"


def test_infer_drop_cap_letter_for_researchers() -> None:
    assert infer_drop_cap_letter("ESEARCHERS have been seeking") == "R"
