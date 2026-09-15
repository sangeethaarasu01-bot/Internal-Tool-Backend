"""Tests for section semantic type in LLM mapping contract."""

from __future__ import annotations

import json

from app.models.semantic_mapping import MappedSemanticNode
from app.services.llm.response_parser import parse_llm_mapping_response


def test_section_semantic_type_is_valid() -> None:
    node = MappedSemanticNode(semantic_type="section", text="INTRODUCTION", label="I.")
    assert node.semantic_type == "section"


def test_parse_llm_mapping_accepts_section_nodes() -> None:
    payload = {
        "mapping": {
            "front": {},
            "body": [
                {
                    "semantic_type": "section",
                    "label": "I.",
                    "text": "INTRODUCTION",
                    "children": [
                        {
                            "semantic_type": "paragraph",
                            "text": "Body text.",
                            "source_block_ids": ["p2_b1"],
                        }
                    ],
                }
            ],
            "back": {},
        },
        "unmapped_content": [],
        "warnings": [],
    }
    result = parse_llm_mapping_response(json.dumps(payload))
    assert result.mapping.body[0].semantic_type == "section"
    assert result.mapping.body[0].children[0].semantic_type == "paragraph"
