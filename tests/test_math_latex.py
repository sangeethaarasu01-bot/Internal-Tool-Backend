"""Tests for math LaTeX normalization and equation labels."""

from app.services.ir_builder import build_display_math, parse_inline_elements
from app.models.ir_schema import IRInlineMathElement
from app.utils.math_latex import (
    is_equation_group_boundary,
    is_plausible_display_equation,
    normalize_display_latex,
    split_equation_label,
)


def test_split_equation_label_numeric() -> None:
    assert split_equation_label("TAN = fTAN(XTAN) (1)") == ("(1)", "TAN = fTAN(XTAN)")


def test_split_equation_label_roman() -> None:
    assert split_equation_label("E = mc^2 (iv)") == ("(iv)", "E = mc^2")


def test_normalize_display_latex_greek() -> None:
    assert r"\mu" in normalize_display_latex("400 μL")


def test_is_plausible_display_equation_rejects_noise() -> None:
    assert is_plausible_display_equation("D") is False
    assert is_plausible_display_equation("X1") is False
    assert is_plausible_display_equation("Fused data—50 × 180.") is False
    assert is_plausible_display_equation("yHPLC TAN = fTAN(XTAN)") is True


def test_is_equation_group_boundary() -> None:
    assert is_equation_group_boundary("yHPLC TAN = fTAN(XTAN)", "yHPLC TF = fTF(XTF)") is True
    assert is_equation_group_boundary("yHPLC", "TAN = fTAN(XTAN)") is False
    assert is_equation_group_boundary("XTAN ∈ {X1, X2, X64 TAN}", "where yHPLC") is True


def test_parse_inline_elements_greek_mu() -> None:
    elements = parse_inline_elements("400 μL of EGDMA")
    math = [element for element in elements if isinstance(element, IRInlineMathElement)]
    assert len(math) == 1
    assert math[0].latex == r"\mu"


def test_parse_inline_elements_greek_alpha() -> None:
    elements = parse_inline_elements("parameter α is tuned")
    math = [element for element in elements if isinstance(element, IRInlineMathElement)]
    assert len(math) == 1
    assert math[0].latex == r"\alpha"


def test_build_display_math_renders_label() -> None:
    from app.services.layout.semantic_renderer import _render_element

    node = build_display_math("TAN = fTAN(XTAN)", label="(1)")
    rendered = _render_element(node, indent=2)
    assert "<label" in rendered
    assert ">(1)</label>" in rendered
    assert "fTAN" in rendered
