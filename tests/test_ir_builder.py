"""Unit tests for the IR builder and elements[] schema."""

from __future__ import annotations

from app.constants.ir_types import IR_DISPLAY_MATH, IR_HEADING, IR_PARAGRAPH
from app.models.ir_schema import IRInlineMathElement, IRNode, IRTextElement
from app.services.ir_builder import (
    build_abstract,
    build_display_math,
    build_heading,
    build_ir_node,
    build_paragraph,
    parse_inline_elements,
    semantic_type_to_ir,
)


def test_semantic_type_to_ir_maps_paragraph() -> None:
    assert semantic_type_to_ir("PARAGRAPH") == IR_PARAGRAPH


def test_semantic_type_to_ir_maps_equation_to_display_math() -> None:
    assert semantic_type_to_ir("EQUATION") == IR_DISPLAY_MATH


def test_parse_inline_elements_plain_text() -> None:
    elements = parse_inline_elements("Hello world.")
    assert len(elements) == 1
    assert isinstance(elements[0], IRTextElement)
    assert elements[0].value == "Hello world."


def test_parse_inline_elements_dollar_math() -> None:
    elements = parse_inline_elements("The energy is given by $E=mc^2$.")
    assert len(elements) == 3
    assert elements[0].value == "The energy is given by "
    assert isinstance(elements[1], IRInlineMathElement)
    assert elements[1].latex == "E=mc^2"
    assert elements[2].value == "."


def test_parse_inline_elements_r_squared() -> None:
    elements = parse_inline_elements("The R^2 value is high.")
    math_elements = [e for e in elements if isinstance(e, IRInlineMathElement)]
    assert len(math_elements) == 1
    assert math_elements[0].latex == "R^2"


def test_parse_inline_elements_multiple_r_squared() -> None:
    elements = parse_inline_elements("values R^2, R^2")
    math_elements = [e for e in elements if isinstance(e, IRInlineMathElement)]
    assert len(math_elements) == 2
    assert all(e.latex == "R^2" for e in math_elements)


def test_parse_inline_elements_air2plane_no_false_positive() -> None:
    elements = parse_inline_elements("AIR^2PLANE")
    assert len(elements) == 1
    assert isinstance(elements[0], IRTextElement)
    assert elements[0].value == "AIR^2PLANE"
    assert not any(isinstance(e, IRInlineMathElement) for e in elements)


def test_parse_inline_elements_pair2ing_no_false_positive() -> None:
    elements = parse_inline_elements("PAIR^2ING")
    assert len(elements) == 1
    assert isinstance(elements[0], IRTextElement)
    assert not any(isinstance(e, IRInlineMathElement) for e in elements)


def test_parse_inline_elements_chemistry_formulas_are_plain_text() -> None:
    for text in ("NiCo2O4 nanoparticles", "Gd2O3", "CuO and CO2"):
        elements = parse_inline_elements(text)
        assert all(isinstance(e, IRTextElement) for e in elements)
        assert not any(isinstance(e, IRInlineMathElement) for e in elements)


def test_parse_inline_elements_t_sne_is_plain_text() -> None:
    elements = parse_inline_elements("We used t-SNE for clustering.")
    assert all(isinstance(e, IRTextElement) for e in elements)
    assert not any(isinstance(e, IRInlineMathElement) for e in elements)


def test_parse_inline_elements_mse_is_plain_text() -> None:
    elements = parse_inline_elements("The mse was low.")
    assert all(isinstance(e, IRTextElement) for e in elements)
    assert not any(isinstance(e, IRInlineMathElement) for e in elements)


def test_parse_inline_elements_dollar_only_math() -> None:
    elements = parse_inline_elements("$E=mc^2$")
    math_elements = [e for e in elements if isinstance(e, IRInlineMathElement)]
    assert len(math_elements) == 1
    assert math_elements[0].latex == "E=mc^2"


def test_build_paragraph_has_elements_array() -> None:
    node = build_paragraph("Simple paragraph text.")
    assert node.type == IR_PARAGRAPH
    assert len(node.elements) == 1
    assert node.elements[0].type == "text"
    assert node.elements[0].value == "Simple paragraph text."


def test_build_display_math_has_latex_field() -> None:
    node = build_display_math("TAN = fTAN(XTAN)")
    assert node.type == IR_DISPLAY_MATH
    assert node.latex == "TAN = fTAN(XTAN)"
    assert node.elements == []


def test_build_heading_has_level_and_elements() -> None:
    node = build_heading("I. INTRODUCTION", level=1)
    assert node.type == IR_HEADING
    assert node.level == 1
    assert node.elements[0].value == "I. INTRODUCTION"


def test_build_ir_node_equation_becomes_display_math() -> None:
    node = build_ir_node("EQUATION", "yHPLC TAN = fTAN(XTAN)")
    assert node.type == IR_DISPLAY_MATH
    assert node.latex is not None
    assert "fTAN" in node.latex


def test_build_abstract_wraps_paragraph_child() -> None:
    abstract = build_abstract("Abstract—In this approach we show results.")
    assert abstract.type == "abstract"
    assert len(abstract.children) == 1
    assert abstract.children[0].type == IR_PARAGRAPH
    assert abstract.children[0].elements[0].value.startswith("Abstract")


def test_ir_node_text_property_concatenates_elements() -> None:
    node = IRNode(
        type=IR_PARAGRAPH,
        elements=[
            IRTextElement(value="Energy "),
            IRInlineMathElement(latex="E=mc^2"),
        ],
    )
    assert node.text == "Energy E=mc^2"


def test_ir_node_tag_maps_to_jats() -> None:
    node = build_paragraph("text")
    assert node.tag == "p"

    eq = build_display_math("x=1")
    assert eq.tag == "disp-formula"


def test_ir_node_to_json_dict_excludes_none() -> None:
    node = build_paragraph("hello", source_block_ids=["p1_b1"], page_numbers=[1])
    payload = node.to_json_dict()
    assert payload["type"] == IR_PARAGRAPH
    assert payload["elements"][0]["type"] == "text"
    assert payload["source_block_ids"] == ["p1_b1"]
    assert "latex" not in payload


def test_inline_math_in_paragraph_not_display_math() -> None:
    """$x_1 + x_2$ inside a sentence must be inline_math, not display_math."""
    node = build_paragraph("The sum $x_1 + x_2$ is shown.")
    assert node.type == IR_PARAGRAPH
    math_elements = [e for e in node.elements if isinstance(e, IRInlineMathElement)]
    assert len(math_elements) == 1
    assert math_elements[0].latex == "x_1 + x_2"


def test_standalone_equation_becomes_display_math() -> None:
    """Standalone equation line TAN = f(X) must be display_math."""
    node = build_ir_node("EQUATION", "TAN = f(X)")
    assert node.type == IR_DISPLAY_MATH
    assert node.latex == "TAN = f(X)"
    assert node.elements == []
