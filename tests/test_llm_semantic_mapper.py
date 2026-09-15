"""Unit tests for LLM semantic mapping (fake provider only — no real API calls)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.models.semantic_mapping import SemanticMappingResult
from app.services.llm.providers.base import LLMProviderError
from app.services.llm.response_parser import LLMResponseParseError, parse_llm_mapping_response
from app.services.llm_semantic_mapper import SemanticMappingError, map_semantic_content

VALID_MAPPING = {
    "mapping": {
        "front": {
            "title": {
                "semantic_type": "metadata",
                "text": "My Paper",
                "source_block_ids": ["p1_b1"],
                "source_node_ids": ["node_title"],
            }
        },
        "body": [
            {
                "semantic_type": "paragraph",
                "text": "Body paragraph.",
                "source_block_ids": ["p2_b10"],
                "template_path": "body/sec/p",
                "elements": [{"type": "text", "value": "Body paragraph."}],
            },
            {
                "semantic_type": "display_math",
                "latex": "TAN = fTAN(XTAN)",
                "source_block_ids": ["p6_b43"],
                "template_path": "body/disp-formula",
            },
            {
                "semantic_type": "inline_math",
                "latex": "E=mc^2",
                "source_block_ids": ["p3_b5"],
                "elements": [{"type": "inline_math", "latex": "E=mc^2"}],
            },
            {
                "semantic_type": "figure",
                "label": "Fig. 1",
                "text": "Setup diagram",
                "source_block_ids": ["p4_fig"],
                "children": [
                    {
                        "semantic_type": "caption",
                        "text": "Fig. 1. Setup",
                        "source_block_ids": ["p4_cap"],
                    }
                ],
            },
            {
                "semantic_type": "table",
                "label": "TABLE I",
                "rows": [["A", "B"], ["1", "2"]],
                "source_block_ids": ["p3_tbl"],
            },
        ],
        "back": {
            "references": [
                {
                    "semantic_type": "reference",
                    "label": "[1]",
                    "text": "[1] Smith et al., 2020.",
                    "source_block_ids": ["p8_b2"],
                }
            ]
        },
    },
    "unmapped_content": [
        {
            "source_block_ids": ["p9_x"],
            "reason": "No matching template field",
            "ir_type": "unknown",
        }
    ],
    "warnings": ["Partial mapping"],
}


class FakeLLMProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        self.call_count += 1
        if not self._responses:
            raise LLMProviderError("No more fake responses")
        return self._responses.pop(0)


@pytest.fixture
def template_schema() -> dict:
    return {
        "template_name": "test",
        "template_source": "fixture.xml",
        "root_tag": "article",
        "section_boundaries": {
            "front": {"direct_children": ["journal-meta"], "descendants": ["article-title"]},
            "body": {"direct_children": ["sec"], "descendants": ["p", "disp-formula"]},
            "back": {"direct_children": ["ref-list"], "descendants": ["ref"]},
        },
        "scope_markers": {"full": ["front", "body", "back"]},
        "required_paths": [],
        "tags": {},
        "llm_hints": {"must_not_hallucinate": ["doi"], "prefer_extract_over_generate": True},
    }


@pytest.fixture
def scoped_ir() -> dict:
    return {
        "pipeline_version": "2.0.0",
        "front": {"title": {"type": "title", "source_block_ids": ["p1_b1"]}},
        "body": {"sections": [], "loose_paragraphs": []},
        "back": {"references": []},
        "unknown": [],
        "completeness": {},
    }


def test_parse_valid_json_response() -> None:
    payload = parse_llm_mapping_response(json.dumps(VALID_MAPPING))
    assert len(payload.mapping.body) == 5
    assert payload.mapping.body[1].latex == "TAN = fTAN(XTAN)"
    assert payload.unmapped_content[0].reason.startswith("No matching")


def test_reject_invalid_json() -> None:
    with pytest.raises(LLMResponseParseError, match="Invalid JSON"):
        parse_llm_mapping_response("{not json}")


def test_reject_xml_response() -> None:
    with pytest.raises(LLMResponseParseError, match="XML"):
        parse_llm_mapping_response('<article><front></front></article>')


def test_reject_markdown_response() -> None:
    with pytest.raises(LLMResponseParseError, match="Markdown"):
        parse_llm_mapping_response("```json\n" + json.dumps(VALID_MAPPING) + "\n```")


def test_reject_missing_mapping_field() -> None:
    with pytest.raises(LLMResponseParseError, match="mapping"):
        parse_llm_mapping_response(json.dumps({"warnings": []}))


def test_reject_unexpected_top_level_keys() -> None:
    data = dict(VALID_MAPPING)
    data["xml"] = "<article/>"
    with pytest.raises(LLMResponseParseError, match="unexpected"):
        parse_llm_mapping_response(json.dumps(data))


def test_reject_unknown_semantic_type() -> None:
    data = json.loads(json.dumps(VALID_MAPPING))
    data["mapping"]["body"][0]["semantic_type"] = "not_a_real_type"
    with pytest.raises(LLMResponseParseError, match="schema validation"):
        parse_llm_mapping_response(json.dumps(data))


@patch("app.services.llm_semantic_mapper.log_llm_call")
def test_map_semantic_content_valid(
    mock_log,
    template_schema: dict,
    scoped_ir: dict,
) -> None:
    provider = FakeLLMProvider([json.dumps(VALID_MAPPING)])
    result = map_semantic_content(
        document_id="doc123",
        scope="full",
        ir=scoped_ir,
        template_schema=template_schema,
        provider=provider,
        max_retries=2,
    )
    assert isinstance(result, SemanticMappingResult)
    assert result.prompt_version == "v1"
    assert result.document_id == "doc123"
    assert result.mapping.body[2].latex == "E=mc^2"
    assert result.mapping.body[3].label == "Fig. 1"
    assert result.mapping.body[4].rows == [["A", "B"], ["1", "2"]]
    assert result.mapping.back["references"][0]["label"] == "[1]"
    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["success"] is True


@patch("app.services.llm_semantic_mapper.log_llm_call")
def test_source_block_ids_preserved(mock_log, template_schema: dict, scoped_ir: dict) -> None:
    provider = FakeLLMProvider([json.dumps(VALID_MAPPING)])
    result = map_semantic_content(
        document_id="doc123",
        scope="full",
        ir=scoped_ir,
        template_schema=template_schema,
        provider=provider,
    )
    assert result.mapping.body[0].source_block_ids == ["p2_b10"]


@patch("app.services.llm_semantic_mapper.log_llm_call")
def test_provider_failure_limited_retries(mock_log, template_schema: dict, scoped_ir: dict) -> None:
    provider = FakeLLMProvider([])

    def fail_complete(**kwargs):
        provider.call_count += 1
        raise LLMProviderError("transient error")

    provider.complete = fail_complete  # type: ignore[method-assign]

    with pytest.raises(SemanticMappingError, match="transient"):
        map_semantic_content(
            document_id="doc123",
            scope="full",
            ir=scoped_ir,
            template_schema=template_schema,
            provider=provider,
            max_retries=2,
        )
    assert provider.call_count == 2
    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["success"] is False


@patch("app.services.llm_semantic_mapper.log_llm_call")
def test_retry_on_invalid_json_then_success(mock_log, template_schema: dict, scoped_ir: dict) -> None:
    provider = FakeLLMProvider(["{bad json", json.dumps(VALID_MAPPING)])
    result = map_semantic_content(
        document_id="doc123",
        scope="full",
        ir=scoped_ir,
        template_schema=template_schema,
        provider=provider,
        max_retries=2,
    )
    assert provider.call_count == 2
    assert result.mapping.body[0].text == "Body paragraph."


@patch("app.services.llm_semantic_mapper.log_llm_call")
def test_prompt_version_included(mock_log, template_schema: dict, scoped_ir: dict) -> None:
    provider = FakeLLMProvider([json.dumps(VALID_MAPPING)])
    result = map_semantic_content(
        document_id="doc123",
        scope="front",
        ir=scoped_ir,
        template_schema=template_schema,
        provider=provider,
    )
    assert result.prompt_version == "v1"
