"""Tests for scope_resolver.py — front / body / back / full filtering."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.template_schema import TemplateSchema
from app.services.scope_resolver import (
    InvalidScopeError,
    filter_ir,
    filter_template_schema,
    normalize_scope,
    resolve_allowed_sections,
    resolve_scope,
)
from app.services.template_parser import TemplateParser

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_XML = ROOT / "tests" / "fixtures" / "1458242.xml"
KNOWN_TAGS = ROOT / "app" / "constants" / "jats_2_0_known_tags.json"


@pytest.fixture
def template_schema_dict() -> dict:
    schema = TemplateParser(FIXTURE_XML, known_tags_path=KNOWN_TAGS).parse()
    return schema.model_dump(mode="json")


@pytest.fixture
def sample_ir() -> dict:
    """SemanticDocument-shaped IR with content in all three sections."""
    return {
        "pipeline_version": "2.0.0",
        "front": {
            "title": {"type": "title", "elements": [{"type": "text", "value": "My Paper"}]},
            "abstract": {
                "type": "abstract",
                "children": [{"type": "paragraph", "elements": [{"type": "text", "value": "Abstract text."}]}],
            },
            "authors": [{"type": "author", "elements": [{"type": "text", "value": "Jane Doe"}]}],
            "affiliations": [],
            "keywords": None,
            "journal_header": None,
            "page_number": None,
            "date_history": None,
            "corresponding_author": None,
            "other": [],
        },
        "body": {
            "sections": [
                {
                    "heading": "I. INTRODUCTION",
                    "heading_element": {
                        "type": "heading",
                        "elements": [{"type": "text", "value": "I. INTRODUCTION"}],
                    },
                    "level": 1,
                    "paragraphs": [],
                    "subsections": [],
                    "content": [
                        {
                            "type": "paragraph",
                            "elements": [{"type": "text", "value": "Body paragraph."}],
                        }
                    ],
                    "content_source_block_ids": [],
                }
            ],
            "loose_paragraphs": [],
        },
        "back": {
            "reference_list": None,
            "references": [
                {
                    "type": "reference",
                    "elements": [{"type": "text", "value": "[1] Smith et al."}],
                }
            ],
            "other": [],
        },
        "unknown": [{"type": "unknown", "unknown_reason": "orphan block"}],
        "completeness": {"raw_character_count": 100},
    }


def test_normalize_scope_front_variants() -> None:
    assert normalize_scope("front") == "front"
    assert normalize_scope("Front Meta Only") == "front"
    assert normalize_scope("frontmatter") == "front"
    assert normalize_scope("FRONT") == "front"


def test_normalize_scope_back_variants() -> None:
    assert normalize_scope("back") == "back"
    assert normalize_scope("back meta only") == "back"
    assert normalize_scope("Back Matter") == "back"


def test_normalize_scope_body_variants() -> None:
    assert normalize_scope("body") == "body"
    assert normalize_scope("Body Matter") == "body"
    assert normalize_scope("body only") == "body"
    assert normalize_scope("BODY") == "body"


def test_normalize_scope_full_variants() -> None:
    assert normalize_scope("full") == "full"
    assert normalize_scope("complete document") == "full"
    assert normalize_scope("ALL") == "full"


def test_normalize_scope_garbage_raises() -> None:
    with pytest.raises(InvalidScopeError):
        normalize_scope("sideways")


def test_resolve_allowed_sections() -> None:
    assert resolve_allowed_sections("front") == ["front"]
    assert resolve_allowed_sections("body") == ["body"]
    assert resolve_allowed_sections("back") == ["back"]
    assert resolve_allowed_sections("full") == ["front", "body", "back"]


def test_filter_front_removes_body_and_back(sample_ir: dict) -> None:
    filtered, dropped = filter_ir(sample_ir, ["front"])
    assert filtered["front"]["title"] is not None
    assert filtered["body"]["sections"] == []
    assert filtered["back"]["references"] == []
    assert filtered["unknown"] == []
    assert dropped > 0


def test_filter_body_removes_front_and_back(sample_ir: dict) -> None:
    filtered, dropped = filter_ir(sample_ir, ["body"])
    assert filtered["front"]["title"] is None
    assert len(filtered["body"]["sections"]) == 1
    assert filtered["back"]["references"] == []
    assert filtered["unknown"] == []
    assert dropped > 0


def test_filter_back_removes_front_and_body(sample_ir: dict) -> None:
    filtered, dropped = filter_ir(sample_ir, ["back"])
    assert filtered["front"]["title"] is None
    assert filtered["body"]["sections"] == []
    assert len(filtered["back"]["references"]) == 1
    assert filtered["unknown"] == []
    assert dropped > 0


def test_filter_full_is_noop(sample_ir: dict) -> None:
    filtered, dropped = filter_ir(sample_ir, ["front", "body", "back"])
    assert filtered["front"]["title"] is not None
    assert len(filtered["body"]["sections"]) == 1
    assert len(filtered["back"]["references"]) == 1
    assert len(filtered["unknown"]) == 1
    assert dropped == 0


def test_filter_front_has_zero_body_back_nodes(sample_ir: dict) -> None:
    result = resolve_scope("front", {}, sample_ir)
    filtered = result["filtered_ir"]
    assert _count_body_nodes(filtered["body"]) == 0
    assert _count_back_nodes(filtered["back"]) == 0


def test_filter_template_schema_required_paths(template_schema_dict: dict) -> None:
    filtered = filter_template_schema(template_schema_dict, ["front"])
    for path in filtered["required_paths"]:
        assert path.startswith("front/")
    assert "body/sec" not in filtered["required_paths"]
    assert "back/ref-list" not in filtered["required_paths"]
    assert "front" in filtered["section_boundaries"]
    assert "body" not in filtered["section_boundaries"]


def test_filter_template_schema_preserves_cardinality(template_schema_dict: dict) -> None:
    original = template_schema_dict["tags"]["disp-formula"]["cardinality"]
    filtered = filter_template_schema(template_schema_dict, ["body"])
    assert filtered["tags"]["disp-formula"]["cardinality"] == original


def test_resolve_scope_full_returns_all_sections(
    template_schema_dict: dict,
    sample_ir: dict,
) -> None:
    result = resolve_scope("full", template_schema_dict, sample_ir)
    assert result["resolved_scope"] == "full"
    assert result["allowed_sections"] == ["front", "body", "back"]
    assert result["dropped_element_count"] == 0
    assert result["filtered_ir"]["front"]["title"] is not None
    assert len(result["filtered_ir"]["body"]["sections"]) == 1


def test_resolve_scope_missing_back_boundary_returns_warning(sample_ir: dict) -> None:
    schema = {
        "template_name": "minimal",
        "template_source": "test",
        "root_tag": "article",
        "section_boundaries": {"front": {"direct_children": ["journal-meta"], "descendants": []}},
        "scope_markers": {"front": ["front"], "full": ["front", "body", "back"]},
        "required_paths": [],
        "tags": {},
        "llm_hints": {"must_not_hallucinate": [], "prefer_extract_over_generate": True},
    }
    result = resolve_scope("back", schema, sample_ir)
    assert result["resolved_scope"] == "back"
    assert any("back" in warning for warning in result["warnings"])
    assert result["filtered_ir"]["front"]["title"] is None
    assert len(result["filtered_ir"]["back"]["references"]) == 1


def test_flat_ir_elements_with_section_tags() -> None:
    ir = {
        "elements": [
            {"type": "title", "section": "front", "elements": [{"type": "text", "value": "T"}]},
            {"type": "paragraph", "section": "body", "elements": [{"type": "text", "value": "P"}]},
            {"type": "reference", "section": "back", "elements": [{"type": "text", "value": "R"}]},
            {"type": "paragraph", "section": "body", "elements": [{"type": "text", "value": "P2"}]},
        ]
    }
    filtered, dropped = filter_ir(ir, ["front"])
    assert len(filtered["elements"]) == 1
    assert filtered["elements"][0]["section"] == "front"
    assert dropped == 3


def test_flat_ir_missing_section_tag_is_dropped_and_counted() -> None:
    ir = {
        "elements": [
            {"type": "paragraph", "section": "front", "elements": []},
            {"type": "paragraph", "elements": [{"type": "text", "value": "orphan"}]},
        ]
    }
    filtered, dropped = filter_ir(ir, ["front"])
    assert len(filtered["elements"]) == 1
    assert dropped == 1


def test_filter_ir_does_not_mutate_original(sample_ir: dict) -> None:
    import copy

    original = copy.deepcopy(sample_ir)
    filter_ir(sample_ir, ["front"])
    assert sample_ir == original


def test_filter_template_schema_does_not_mutate_original(template_schema_dict: dict) -> None:
    import copy

    original = copy.deepcopy(template_schema_dict)
    filter_template_schema(template_schema_dict, ["body"])
    assert template_schema_dict == original


def test_resolve_scope_body_matter(
    template_schema_dict: dict,
    sample_ir: dict,
) -> None:
    result = resolve_scope("body", template_schema_dict, sample_ir)
    assert result["resolved_scope"] == "body"
    assert result["allowed_sections"] == ["body"]
    assert result["filtered_ir"]["front"]["title"] is None
    assert len(result["filtered_ir"]["body"]["sections"]) == 1
    assert result["filtered_ir"]["back"]["references"] == []


def test_resolve_scope_front_meta_only_verbose_phrasing(
    template_schema_dict: dict,
    sample_ir: dict,
) -> None:
    result = resolve_scope("Front Meta Only", template_schema_dict, sample_ir)
    assert result["resolved_scope"] == "front"
    assert result["allowed_sections"] == ["front"]
    assert _count_body_nodes(result["filtered_ir"]["body"]) == 0


def _count_body_nodes(body: dict) -> int:
    from app.services.scope_resolver import _count_body_nodes as count

    return count(body)


def _count_back_nodes(back: dict) -> int:
    from app.services.scope_resolver import _count_back_nodes as count

    return count(back)
