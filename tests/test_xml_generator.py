"""Tests for Phase 3 template-driven XML generation."""

from __future__ import annotations

from pathlib import Path

from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.xml_generator import generate_jats_xml, generate_jats_xml_from_ir

FIXTURE_TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "1458242.xml"

SAMPLE_IR = {
    "front": {
        "title": {
            "type": "title",
            "elements": [{"type": "text", "value": "Generated Paper Title"}],
            "source_block_ids": ["p1_b1"],
        },
        "abstract": {
            "type": "abstract",
            "elements": [{"type": "text", "value": "This is the abstract."}],
            "source_block_ids": ["p1_b2"],
        },
        "keywords": {
            "type": "keywords",
            "elements": [{"type": "text", "value": "sensor, tea"}],
            "source_block_ids": ["p1_b3"],
        },
        "authors": [],
        "affiliations": [],
    },
    "body": {
        "sections": [
            {
                "heading": "INTRODUCTION",
                "heading_element": {
                    "type": "heading",
                    "label": "I.",
                    "elements": [{"type": "text", "value": "INTRODUCTION"}],
                    "source_block_ids": ["p2_b1"],
                },
                "level": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "elements": [{"type": "text", "value": "Intro paragraph."}],
                        "source_block_ids": ["p2_b2"],
                    },
                    {
                        "type": "display_math",
                        "latex": "TAN = fTAN(XTAN)",
                        "label": "(1)",
                        "source_block_ids": ["p6_b43"],
                    },
                ],
                "subsections": [],
                "paragraphs": [],
                "content_source_block_ids": [],
            }
        ],
        "loose_paragraphs": [],
    },
    "back": {
        "references": [
            {
                "type": "reference",
                "elements": [{"type": "text", "value": "[1] Smith et al., 2020."}],
                "source_block_ids": ["p8_b1"],
            }
        ],
        "reference_list": None,
        "other": [],
    },
}


def test_ir_to_semantic_mapping_builds_sections() -> None:
    mapping = ir_to_semantic_mapping(SAMPLE_IR)
    assert mapping.front["title"]["text"] == "Generated Paper Title"
    assert len(mapping.body) == 1
    assert mapping.body[0].semantic_type == "heading"
    assert mapping.body[0].label == "I."
    assert len(mapping.body[0].children) == 2


def test_generate_jats_xml_from_template_and_ir() -> None:
    xml = generate_jats_xml_from_ir(FIXTURE_TEMPLATE, SAMPLE_IR)
    assert xml.startswith("<?xml")
    assert "<article-title>Generated Paper Title</article-title>" in xml
    assert "<label>I.</label>" in xml
    assert "<title>INTRODUCTION</title>" in xml
    assert "Intro paragraph." in xml
    assert "<disp-formula>" in xml
    assert "TAN = fTAN(XTAN)" in xml
    assert "<label>(1)</label>" in xml
    assert "<ref " in xml
    assert "Smith et al." in xml


def test_generate_jats_xml_with_mapping_body() -> None:
    mapping = ir_to_semantic_mapping(SAMPLE_IR)
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert "<kwd>sensor</kwd>" in xml
    assert "<kwd>tea</kwd>" in xml


def test_generate_jats_xml_with_illegal_inline_control_char() -> None:
    from app.models.semantic_mapping import MappedInlineElement, MappedSemanticNode, SemanticMappingBody

    mapping = SemanticMappingBody(
        front={
            "title": {
                "semantic_type": "metadata",
                "text": "Title",
                "source_block_ids": ["p1_b1"],
            }
        },
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                source_block_ids=["p4_b1"],
                elements=[MappedInlineElement(type="text", value="bad\x00char\x08here")],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert "badcharhere" in xml
    assert "\x00" not in xml


def test_generate_jats_xml_nested_sections() -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="section",
                label="I.",
                text="INTRODUCTION",
                children=[
                    MappedSemanticNode(
                        semantic_type="section",
                        label="A.",
                        text="Subsection",
                        children=[
                            MappedSemanticNode(
                                semantic_type="paragraph",
                                text="Nested paragraph.",
                                source_block_ids=["p3_b1"],
                            )
                        ],
                    )
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert xml.count("<sec") >= 2
    assert "<label>A.</label>" in xml
    assert "Nested paragraph." in xml
