"""Heuristic vs LLM mapping orchestration (isolated from extraction/XML generators)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.models.semantic_mapping import SemanticMappingBody, SemanticMappingResult
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.llm.providers.base import LLMConfigurationError
from app.services.llm_semantic_mapper import SemanticMappingError
from app.services.mapping_orchestration import (
    build_heuristic_semantic_mapping,
    finalize_mapping_for_xml,
    resolve_semantic_mapping_for_generate_xml,
)
from tests.test_llm_semantic_mapper import VALID_MAPPING, FakeLLMProvider


MINIMAL_IR = {
    "front": {
        "title": {"type": "title", "text": "Sample Article", "source_block_ids": ["p1_t"]},
        "abstract": {"type": "abstract", "text": "Abstract text.", "source_block_ids": ["p1_a"]},
    },
    "body": {
        "sections": [
            {
                "level": 1,
                "heading": "Introduction",
                "heading_element": {"text": "Introduction", "source_block_ids": ["p2_h"]},
                "content": [
                    {
                        "type": "paragraph",
                        "text": "Body paragraph one.",
                        "source_block_ids": ["p2_b1"],
                    }
                ],
                "subsections": [],
            }
        ],
        "loose_paragraphs": [],
    },
    "back": {
        "references": [
            {
                "type": "reference",
                "text": "[1] A. Author, 2020.",
                "label": "[1]",
                "source_block_ids": ["p9_r1"],
            }
        ]
    },
}


def test_build_heuristic_matches_ir_adapter_directly() -> None:
    legacy = ir_to_semantic_mapping(MINIMAL_IR)
    isolated = build_heuristic_semantic_mapping(MINIMAL_IR)
    assert legacy.model_dump(mode="json") == isolated.model_dump(mode="json")


def test_heuristic_mode_never_calls_llm_mapper() -> None:
    with patch("app.services.mapping_orchestration.map_semantic_content") as mock_llm:
        result = resolve_semantic_mapping_for_generate_xml(
            extraction_id="job-1",
            resolved_scope="full",
            filtered_ir=MINIMAL_IR,
            filtered_template_schema={"root_tag": "article"},
            use_llm=False,
            llm_fallback=True,
        )
    mock_llm.assert_not_called()
    assert result.mapping_source == "ir_adapter"
    assert result.llm_attempted is False
    assert result.llm_succeeded is False
    assert any("deterministic IR adapter" in w for w in result.warnings)


@patch("app.services.mapping_orchestration.is_llm_configured", return_value=False)
def test_use_llm_without_api_key_falls_back_to_heuristic(_mock_cfg: object) -> None:
    with patch("app.services.mapping_orchestration.map_semantic_content") as mock_llm:
        result = resolve_semantic_mapping_for_generate_xml(
            extraction_id="job-1",
            resolved_scope="full",
            filtered_ir=MINIMAL_IR,
            filtered_template_schema={},
            use_llm=True,
            llm_fallback=True,
        )
    mock_llm.assert_not_called()
    assert result.mapping_source == "ir_adapter"
    assert any("LLM not configured" in w for w in result.warnings)


@patch("app.services.mapping_orchestration.is_llm_configured", return_value=True)
def test_llm_success_sets_mapping_source_llm(_mock_cfg: object) -> None:
    payload = SemanticMappingResult(
        document_id="job-1",
        scope="full",
        prompt_version="v1",
        mapping=SemanticMappingBody.model_validate(VALID_MAPPING["mapping"]),
        unmapped_content=[],
        warnings=["from-llm"],
    )

    with patch(
        "app.services.mapping_orchestration.map_semantic_content",
        return_value=payload,
    ) as mock_llm:
        result = resolve_semantic_mapping_for_generate_xml(
            extraction_id="job-1",
            resolved_scope="full",
            filtered_ir=MINIMAL_IR,
            filtered_template_schema={"root_tag": "article"},
            use_llm=True,
            llm_fallback=True,
        )
    mock_llm.assert_called_once()
    assert result.mapping_source == "llm"
    assert result.llm_succeeded is True
    assert result.prompt_version == "v1"
    assert result.semantic_record is not None


@patch("app.services.mapping_orchestration.is_llm_configured", return_value=True)
def test_llm_failure_without_fallback_raises(_mock_cfg: object) -> None:
    with patch(
        "app.services.mapping_orchestration.map_semantic_content",
        side_effect=SemanticMappingError("timeout"),
    ):
        with pytest.raises(SemanticMappingError):
            resolve_semantic_mapping_for_generate_xml(
                extraction_id="job-1",
                resolved_scope="full",
                filtered_ir=MINIMAL_IR,
                filtered_template_schema={},
                use_llm=True,
                llm_fallback=False,
            )


@patch("app.services.mapping_orchestration.is_llm_configured", return_value=True)
def test_llm_failure_with_fallback_uses_heuristic(_mock_cfg: object) -> None:
    with patch(
        "app.services.mapping_orchestration.map_semantic_content",
        side_effect=SemanticMappingError("rate limit"),
    ):
        result = resolve_semantic_mapping_for_generate_xml(
            extraction_id="job-1",
            resolved_scope="full",
            filtered_ir=MINIMAL_IR,
            filtered_template_schema={},
            use_llm=True,
            llm_fallback=True,
        )
    assert result.mapping_source == "ir_adapter_fallback"
    assert result.llm_attempted is True
    assert result.llm_succeeded is False
    expected = build_heuristic_semantic_mapping(MINIMAL_IR)
    assert result.mapping_body.model_dump(mode="json") == expected.model_dump(mode="json")


def test_finalize_mapping_fills_references_from_ir() -> None:
    llm_body = SemanticMappingBody(front={}, body=[], back={})
    finalized = finalize_mapping_for_xml(llm_body, MINIMAL_IR)
    refs = finalized.back.get("references") or []
    assert len(refs) == 1
    assert "[1]" in (refs[0].get("text") or refs[0].get("label") or "")


def test_map_semantic_content_integration_with_fake_provider() -> None:
    from app.services.llm_semantic_mapper import map_semantic_content

    provider = FakeLLMProvider([json.dumps(VALID_MAPPING)])
    result = map_semantic_content(
        document_id="job-x",
        scope="full",
        ir=MINIMAL_IR,
        template_schema={"root_tag": "article"},
        provider=provider,
    )
    assert result.mapping.body
    assert provider.call_count == 1
