"""PDF span styles → IR elements → JATS inline markup."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.models.extraction import TextBlock, TextLine, TextSpan
from app.models.semantic_mapping import MappedInlineElement, MappedSemanticNode, SemanticMappingBody
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.xml_generator import generate_jats_xml
from app.utils.span_inline import inline_elements_from_text_block

ROOT = Path(__file__).resolve().parent.parent
JATS_FIXTURE = ROOT / "tests" / "fixtures" / "minimal_template.xml"
_BBOX = [0.0, 0.0, 100.0, 12.0]


def test_span_flags_emit_superscript_element() -> None:
    block = TextBlock(
        block_id="p1_b1",
        type="text",
        bbox=_BBOX,
        text="practices of many.2",
        lines=[
            TextLine(
                line_id="l1",
                bbox=_BBOX,
                text="practices of many.2",
                spans=[
                    TextSpan(text="practices of many.", bbox=_BBOX, flags=0, size=11.0),
                    TextSpan(text="2", bbox=_BBOX, flags=1, size=7.5),
                ],
            )
        ],
    )
    elements = inline_elements_from_text_block(block)
    assert any(getattr(e, "superscript", False) and e.value == "2" for e in elements)
    assert any(e.value == "practices of many." and not getattr(e, "superscript", False) for e in elements)


def test_unicode_superscript_in_span_text_splits_to_sup_element() -> None:
    block = TextBlock(
        block_id="p1_b2",
        type="text",
        bbox=_BBOX,
        text="practices of many.\u00b2",
        lines=[
            TextLine(
                line_id="l1",
                bbox=_BBOX,
                text="practices of many.\u00b2",
                spans=[
                    TextSpan(text="practices of many.\u00b2", bbox=_BBOX, flags=0, size=11.0),
                ],
            )
        ],
    )
    elements = inline_elements_from_text_block(block)
    sup = [e for e in elements if getattr(e, "superscript", False)]
    assert sup and sup[0].value == "2"


def test_ir_superscript_renders_as_jats_sup() -> None:
    ir = {
        "front": {},
        "body": {
            "sections": [
                {
                    "heading": "Intro",
                    "level": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "elements": [
                                {"type": "text", "value": "practices of many."},
                                {"type": "text", "value": "2", "superscript": True},
                            ],
                        }
                    ],
                    "subsections": [],
                }
            ],
            "loose_paragraphs": [],
        },
        "back": {},
    }
    mapping = ir_to_semantic_mapping(ir)
    para = mapping.body[0].children[0]
    assert para.elements[1].superscript is True

    xml = generate_jats_xml(JATS_FIXTURE, mapping)
    root = etree.fromstring(xml.encode("utf-8"))
    sup_nodes = root.xpath("//*[local-name()='sup']")
    assert sup_nodes
    assert sup_nodes[0].text == "2"
    body_text = etree.tostring(root.find(".//{*}body"), encoding="unicode", method="text")
    assert "practices of many." in body_text


def test_bold_italic_wrap_jats_tags() -> None:
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                elements=[
                    MappedInlineElement(type="text", value="emphasis", bold=True, italic=True),
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(JATS_FIXTURE, mapping)
    assert "<bold>" in xml and "<italic>" in xml and "emphasis" in xml
