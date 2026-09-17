"""Tests for deterministic IR → semantic mapping adapter."""

from __future__ import annotations

from app.models.semantic_mapping import SemanticMappingBody
from app.services.ir_semantic_adapter import fill_back_references_from_ir, ir_to_semantic_mapping


def test_section_mapping_uses_content_only_not_duplicate_paragraphs() -> None:
    ir = {
        "front": {},
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
                            "elements": [{"type": "text", "value": "First paragraph."}],
                            "source_block_ids": ["p2_b2"],
                        }
                    ],
                    "paragraphs": [
                        {
                            "type": "paragraph",
                            "elements": [{"type": "text", "value": "First paragraph."}],
                            "source_block_ids": ["p2_b2"],
                        }
                    ],
                    "subsections": [],
                    "content_source_block_ids": ["p2_b2"],
                }
            ],
            "loose_paragraphs": [],
        },
        "back": {},
    }
    mapping = ir_to_semantic_mapping(ir)
    paragraphs = [child for child in mapping.body[0].children if child.semantic_type == "paragraph"]
    assert len(paragraphs) == 1


def test_fill_back_references_from_ir_restores_missing_llm_back_section() -> None:
    ir = {
        "front": {},
        "body": {"sections": [], "loose_paragraphs": []},
        "back": {
            "references": [
                {
                    "type": "reference",
                    "label": "[1]",
                    "elements": [{"type": "text", "value": "[1] A. Author, First paper, IEEE, 2020."}],
                    "source_block_ids": ["p8_b2"],
                }
            ]
        },
    }
    empty_mapping = SemanticMappingBody(front={}, body=[], back={})
    filled = fill_back_references_from_ir(empty_mapping, ir)
    assert len(filled.back["references"]) == 1
    assert filled.back["references"][0]["label"] == "[1]"
