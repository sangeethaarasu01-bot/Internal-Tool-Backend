"""Unit tests for semantic pattern helpers (display-math gating)."""

from __future__ import annotations

from app.constants.ir_types import IR_DISPLAY_MATH, IR_PARAGRAPH
from app.models.ir_schema import IRInlineMathElement
from app.services.ir_builder import build_ir_node
from app.services.layout.semantic_patterns import (
    is_explanatory_math_context,
    is_math_fragment,
    is_standalone_equation_text,
    is_table_continuation_heading,
    looks_like_reference_entry,
    parse_figure_caption,
    paragraph_references_figure,
    split_reference_entries,
)


def test_is_explanatory_math_context_accepts_tf_intro_paragraph() -> None:
    text = (
        "TF, TAN, and TH belong to the group of flavonoids, polyphenols, "
        "and methylxanthines, respectively."
    )
    assert is_explanatory_math_context(text) is True


def test_is_explanatory_math_context_accepts_it_was_observed_paragraph() -> None:
    assert is_explanatory_math_context(
        "It was observed that multimolecular sensing using a single sensor was not enough."
    ) is True


def test_is_math_fragment_rejects_r_squared_prose() -> None:
    assert is_math_fragment("The R^2 value is high.") is False
    assert is_math_fragment("The model achieved R^2 of 0.967.") is False
    assert is_math_fragment("From the R^2 value, quality is predicted.") is False
    assert is_math_fragment("We report R^2 = 0.899 for TAN.") is False


def test_is_math_fragment_accepts_display_math_lines() -> None:
    assert is_math_fragment("TAN = fTAN(XTAN)") is True
    assert is_math_fragment("yHPLC = fTAN(XTAN)") is True
    assert is_math_fragment("X1, X2, X3, ..., X64") is True
    assert is_math_fragment("∑xi = 0") is True


def test_is_math_fragment_accepts_short_variables() -> None:
    from app.utils.math_latex import is_plausible_display_equation

    assert is_math_fragment("X1") is True
    assert is_math_fragment("XTAN") is False
    assert is_math_fragment("TAN = fTAN(XTAN)") is True
    assert is_plausible_display_equation("X1") is False


def test_build_ir_node_r_squared_prose_is_paragraph_with_inline_math() -> None:
    node = build_ir_node("PARAGRAPH", "The R^2 value is high.")
    assert node.type == IR_PARAGRAPH
    math_elements = [e for e in node.elements if isinstance(e, IRInlineMathElement)]
    assert len(math_elements) == 1
    assert math_elements[0].latex == "R^2"
    assert node.text == "The R^2 value is high."


def test_build_ir_node_r_squared_statistics_sentence_is_paragraph() -> None:
    node = build_ir_node("PARAGRAPH", "We report R^2 = 0.899 for TAN.")
    assert node.type == IR_PARAGRAPH
    assert any(isinstance(e, IRInlineMathElement) and e.latex == "R^2" for e in node.elements)


def test_build_ir_node_equation_stays_display_math() -> None:
    node = build_ir_node("EQUATION", "TAN = fTAN(XTAN)")
    assert node.type == IR_DISPLAY_MATH
    assert node.latex == "TAN = fTAN(XTAN)"
    assert node.elements == []


def test_build_ir_node_short_sum_line_is_display_math() -> None:
    node = build_ir_node("PARAGRAPH", "∑xi = 0")
    assert node.type == IR_DISPLAY_MATH
    assert node.latex == "∑xi = 0"


def test_looks_like_reference_entry_accepts_bibliography_items() -> None:
    who_ref = (
        "[1] World Health Organization. Breast Cancer: Prevention and Control. "
        "Accessed: Mar. 16, 2024. [Online]. Available: "
        "https://www.who.int/news-room/fact-sheets/detail/breast-cancer"
    )
    journal_ref = (
        "[2] H. Sung, J. Ferlay, R. L. Siegel, M. Laversanne, I. Soerjomataram, "
        "A. Jemal, and F. Bray, "
        "\u201cGlobal cancer statistics 2020: GLOBOCAN estimates of incidence and mortality worldwide "
        "for 36 cancers in 185 countries,\u201d CA: Cancer J. Clinicians, vol. 71, no. 3, pp. 209\u2013249, "
        "May 2021."
    )
    assert looks_like_reference_entry(who_ref) is True
    assert looks_like_reference_entry(journal_ref) is True


def test_looks_like_reference_entry_rejects_body_prose() -> None:
    intro = (
        "I. INTRODUCTION Breast cancer (BC) ranks as the predominant form of cancer in adults worldwide, "
        "with an alarming rate of over 2.3 million new cases each year, as reported by the "
        "World Health Organization (WHO) 2022."
    )
    survival = (
        "Breast cancer survival rates vary significantly across the globe, with a majority of deaths "
        "occurring in lowand middle-income countries. Early detection is crucial as it leads to a "
        "clinical cure rate of over 90%, but this decreases significantly as the cancer progresses."
    )
    assert looks_like_reference_entry(intro) is False
    assert looks_like_reference_entry(survival) is False


def test_split_reference_entries_splits_bracketed_items() -> None:
    text = (
        "[1] A. Author, First paper, IEEE, 2020. "
        "[2] B. Author, Second paper, IEEE, 2021. "
        "[3] C. Author, Third paper, IEEE, 2022."
    )
    entries = split_reference_entries(text)
    assert len(entries) == 3
    assert entries[0][0] == "[1]"
    assert "First paper" in entries[0][1]
    assert entries[2][0] == "[3]"


def test_is_standalone_equation_text_detects_short_formulas() -> None:
    assert is_standalone_equation_text("TAN = fTAN(XTAN)") is True
    assert is_standalone_equation_text("E = mc^2") is True
    assert is_standalone_equation_text(
        "The model achieved R^2 of 0.967 and performed well on validation data."
    ) is False


def test_is_table_continuation_heading_rejects_math_fragments() -> None:
    assert is_table_continuation_heading("XTAN ∈{X1") is False
    assert is_table_continuation_heading("TAN, X2") is False
    assert is_table_continuation_heading("HPLC VALUES") is True


def test_parse_figure_caption_splits_label_and_body() -> None:
    label, caption = parse_figure_caption("Fig. 1. Reference frames of sensorless controlled SPMSM.")
    assert label == "Fig. 1."
    assert caption == "Reference frames of sensorless controlled SPMSM."


def test_paragraph_references_figure_detects_inline_reference() -> None:
    assert paragraph_references_figure("The setup is shown in Fig. 1 for clarity.", "1") is True
    assert paragraph_references_figure("The setup is shown in Figure 2.", "1") is False
