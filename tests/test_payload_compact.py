"""Tests for LLM payload compaction."""

from __future__ import annotations

from app.services.llm.payload_compact import compact_ir_for_llm, compact_template_schema_for_llm


def test_compact_ir_strips_layout_metadata() -> None:
    ir = {
        "front": {
            "title": {
                "type": "title",
                "elements": [{"type": "text", "value": "Title"}],
                "bbox": [1, 2, 3, 4],
                "page_numbers": [1],
                "confidence": 0.9,
            }
        },
        "body": {"sections": [], "loose_paragraphs": []},
        "back": {"references": []},
        "tagged_output": "<article/>",
        "completeness": {"unknown_element_count": 0},
    }
    compact = compact_ir_for_llm(ir)
    title = compact["front"]["title"]
    assert title["elements"][0]["value"] == "Title"
    assert "bbox" not in title
    assert "tagged_output" not in compact


def test_compact_template_schema_keeps_structure_only() -> None:
    schema = {
        "template_name": "IEEE",
        "section_boundaries": {"body": {"direct_children": ["sec"]}},
        "tags": {"p": {"allowed_children": ["text"]}},
        "required_paths": ["front/article-meta/title-group/article-title"],
    }
    compact = compact_template_schema_for_llm(schema)
    assert compact["template_name"] == "IEEE"
    assert "p" in compact["tag_names"]
    assert "tags" not in compact
