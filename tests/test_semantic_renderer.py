"""Tests for semantic tagged XML rendering."""

from app.models.ir_schema import IRNode, IRTextElement
from app.services.layout.semantic_renderer import _render_element


def test_render_element_strips_illegal_xml_control_chars() -> None:
    element = IRNode(
        type="paragraph",
        elements=[IRTextElement(value="value\x02here")],
        source_block_ids=["p1_b1"],
        page_numbers=[1],
        confidence=1.0,
    )
    rendered = _render_element(element, indent=2)
    assert "\x02" not in rendered
    assert "valuehere" in rendered
