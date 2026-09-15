"""Unit tests for semantic pattern helpers (display-math gating)."""

from __future__ import annotations

from app.constants.ir_types import IR_DISPLAY_MATH, IR_PARAGRAPH
from app.models.ir_schema import IRInlineMathElement
from app.services.ir_builder import build_ir_node
from app.services.layout.semantic_patterns import is_math_fragment, is_standalone_equation_text, split_reference_entries


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
    assert is_math_fragment("X1") is True
    assert is_math_fragment("XTAN") is True


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
