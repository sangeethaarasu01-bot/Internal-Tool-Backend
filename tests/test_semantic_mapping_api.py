"""API tests for POST /api/extractions/{id}/semantic-map (mocked LLM)."""

from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_llm_semantic_mapper import VALID_MAPPING

client = TestClient(app)

EXTRACTION_ID = "507f1f77bcf86cd799439011"

SAMPLE_RESULT = {
    "structure": {
        "semantic": {
            "pipeline_version": "2.0.0",
            "front": {
                "title": {"type": "title", "elements": [{"type": "text", "value": "Title"}]},
                "authors": [],
                "affiliations": [],
                "keywords": None,
                "abstract": None,
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
                        "heading_element": {"type": "heading", "elements": []},
                        "level": 1,
                        "paragraphs": [],
                        "subsections": [],
                        "content": [
                            {
                                "type": "paragraph",
                                "elements": [{"type": "text", "value": "Body"}],
                                "source_block_ids": ["p2_b1"],
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
                        "elements": [{"type": "text", "value": "[1] Ref"}],
                        "source_block_ids": ["p8_b1"],
                    }
                ],
                "other": [],
            },
            "unknown": [],
            "completeness": {},
            "tagged_output": "",
        }
    }
}

TEMPLATE_SCHEMA = {
    "template_name": "fixture",
    "template_source": "1458242.xml",
    "root_tag": "article",
    "section_boundaries": {
        "front": {"direct_children": ["journal-meta", "article-meta"], "descendants": ["article-title"]},
        "body": {"direct_children": ["sec"], "descendants": ["p", "disp-formula", "fig"]},
        "back": {"direct_children": ["ref-list"], "descendants": ["ref"]},
    },
    "scope_markers": {"full": ["front", "body", "back"], "front": ["front"], "body": ["body"], "back": ["back"]},
    "required_paths": ["front/article-meta/title-group/article-title"],
    "tags": {"p": {"allowed_children": ["text"], "allowed_attributes": [], "cardinality": {}, "text_content": True}},
    "llm_hints": {"must_not_hallucinate": ["doi"], "prefer_extract_over_generate": True},
}


def _completed_doc(with_template: bool = True) -> dict:
    from bson import ObjectId

    doc = {
        "_id": ObjectId(EXTRACTION_ID),
        "status": "completed",
        "result": copy.deepcopy(SAMPLE_RESULT),
        "scope": "full",
        "template": None,
    }
    if with_template:
        doc["template"] = {
            "template_id": "tpl_abc",
            "original_filename": "1458242.xml",
            "template_schema": copy.deepcopy(TEMPLATE_SCHEMA),
            "created_at": "2026-01-01T00:00:00Z",
        }
    return doc


class _FakeProvider:
    def __init__(self) -> None:
        self.provider_name = "fake"
        self.model_name = "fake-model"

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        return json.dumps(VALID_MAPPING)


@patch("app.routes.extractions.extractions_col")
@patch("app.services.llm_semantic_mapper.get_llm_provider")
def test_semantic_map_full_scope(mock_get_provider, mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = _completed_doc()
    mock_col.return_value.update_one.return_value = MagicMock()
    mock_get_provider.return_value = _FakeProvider()

    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "full"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == EXTRACTION_ID
    assert data["scope"] == "full"
    assert data["prompt_version"] == "v1"
    assert "mapping" in data
    assert "xml" not in data
    assert isinstance(data["mapping"]["body"], list)


@patch("app.routes.extractions.extractions_col")
@patch("app.services.llm_semantic_mapper.get_llm_provider")
def test_semantic_map_front_scope(mock_get_provider, mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = _completed_doc()
    mock_col.return_value.update_one.return_value = MagicMock()
    mock_get_provider.return_value = _FakeProvider()

    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "front"},
    )
    assert response.status_code == 200
    assert response.json()["scope"] == "front"


@patch("app.routes.extractions.extractions_col")
@patch("app.services.llm_semantic_mapper.get_llm_provider")
def test_semantic_map_body_scope(mock_get_provider, mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = _completed_doc()
    mock_col.return_value.update_one.return_value = MagicMock()
    mock_get_provider.return_value = _FakeProvider()

    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "body"},
    )
    assert response.status_code == 200
    assert response.json()["scope"] == "body"


@patch("app.routes.extractions.extractions_col")
@patch("app.services.llm_semantic_mapper.get_llm_provider")
def test_semantic_map_back_scope(mock_get_provider, mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = _completed_doc()
    mock_col.return_value.update_one.return_value = MagicMock()
    mock_get_provider.return_value = _FakeProvider()

    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "back"},
    )
    assert response.status_code == 200
    assert response.json()["scope"] == "back"


@patch("app.routes.extractions.extractions_col")
def test_semantic_map_missing_template(mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = _completed_doc(with_template=False)
    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "full"},
    )
    assert response.status_code == 400
    assert "template" in response.json()["detail"].lower()


@patch("app.routes.extractions.extractions_col")
def test_semantic_map_missing_extraction(mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = None
    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "full"},
    )
    assert response.status_code == 404


@patch("app.routes.extractions.extractions_col")
def test_semantic_map_invalid_scope(mock_col: MagicMock) -> None:
    mock_col.return_value.find_one.return_value = _completed_doc()
    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "sideways"},
    )
    assert response.status_code == 422


@patch("app.routes.extractions.extractions_col")
@patch("app.routes.extractions.map_semantic_content")
def test_semantic_map_llm_failure(mock_map, mock_col: MagicMock) -> None:
    from app.services.llm_semantic_mapper import SemanticMappingError

    mock_col.return_value.find_one.return_value = _completed_doc()
    mock_map.side_effect = SemanticMappingError("LLM failed")

    response = client.post(
        f"/api/extractions/{EXTRACTION_ID}/semantic-map",
        json={"scope": "full"},
    )
    assert response.status_code == 502
