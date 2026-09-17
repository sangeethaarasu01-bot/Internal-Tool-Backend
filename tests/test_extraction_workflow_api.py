"""API tests for Phase 2A template upload and scope endpoints."""

from __future__ import annotations

import copy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.extraction_workflow import parse_template_xml

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_XML = ROOT / "tests" / "fixtures" / "1458242.xml"

client = TestClient(app)

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
                        "content": [{"type": "paragraph", "elements": [{"type": "text", "value": "Body"}]}],
                        "content_source_block_ids": [],
                    }
                ],
                "loose_paragraphs": [],
            },
            "back": {
                "reference_list": None,
                "references": [{"type": "reference", "elements": [{"type": "text", "value": "[1] Ref"}]}],
                "other": [],
            },
            "unknown": [],
            "completeness": {"raw_character_count": 10},
            "tagged_output": "<article/>",
        }
    }
}


@pytest.fixture
def extraction_id() -> str:
    return "507f1f77bcf86cd799439011"


@pytest.fixture
def completed_doc(extraction_id: str) -> dict:
    return {
        "_id": extraction_id,
        "status": "completed",
        "result": copy.deepcopy(SAMPLE_RESULT),
        "scope": "full",
        "template": None,
    }


def test_parse_template_xml_valid_fixture() -> None:
    schema = parse_template_xml(FIXTURE_XML)
    assert schema["root_tag"] == "article"
    assert "front" in schema["section_boundaries"]


def test_parse_template_xml_invalid_xml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<article><unclosed>", encoding="utf-8")
    with pytest.raises(Exception, match="Invalid XML"):
        parse_template_xml(bad)


@patch("app.routes.extractions.extractions_col")
def test_scope_endpoint_front(mock_col: MagicMock, extraction_id: str, completed_doc: dict) -> None:
    from bson import ObjectId

    oid = ObjectId(extraction_id)
    completed_doc["_id"] = oid
    mock_col.return_value.find_one.return_value = completed_doc
    mock_col.return_value.update_one.return_value = MagicMock()

    response = client.post(
        f"/api/extractions/{extraction_id}/scope",
        json={"scope": "front"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == extraction_id
    assert data["scope"] == "front"
    assert data["allowed_sections"] == ["front"]
    assert data["filtered_ir"]["front"]["title"] is not None
    assert data["filtered_ir"]["body"]["sections"] == []


@patch("app.routes.extractions.extractions_col")
def test_scope_endpoint_body(mock_col: MagicMock, extraction_id: str, completed_doc: dict) -> None:
    from bson import ObjectId

    oid = ObjectId(extraction_id)
    completed_doc["_id"] = oid
    mock_col.return_value.find_one.return_value = completed_doc
    mock_col.return_value.update_one.return_value = MagicMock()

    response = client.post(
        f"/api/extractions/{extraction_id}/scope",
        json={"scope": "body"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["scope"] == "body"
    assert data["allowed_sections"] == ["body"]
    assert data["filtered_ir"]["front"]["title"] is None
    assert len(data["filtered_ir"]["body"]["sections"]) == 1


@patch("app.routes.extractions.extractions_col")
def test_scope_endpoint_full(mock_col: MagicMock, extraction_id: str, completed_doc: dict) -> None:
    from bson import ObjectId

    oid = ObjectId(extraction_id)
    completed_doc["_id"] = oid
    mock_col.return_value.find_one.return_value = completed_doc
    mock_col.return_value.update_one.return_value = MagicMock()

    response = client.post(
        f"/api/extractions/{extraction_id}/scope",
        json={"scope": "full"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed_sections"] == ["front", "body", "back"]
    assert data["dropped_element_count"] == 0


@patch("app.routes.extractions.extractions_col")
def test_scope_endpoint_invalid_scope(mock_col: MagicMock, extraction_id: str, completed_doc: dict) -> None:
    from bson import ObjectId

    oid = ObjectId(extraction_id)
    completed_doc["_id"] = oid
    mock_col.return_value.find_one.return_value = completed_doc

    response = client.post(
        f"/api/extractions/{extraction_id}/scope",
        json={"scope": "sideways"},
    )
    assert response.status_code == 422


@patch("app.routes.extractions.extractions_col")
def test_template_upload_valid_xml(
    mock_col: MagicMock,
    extraction_id: str,
    completed_doc: dict,
    tmp_path: Path,
) -> None:
    from bson import ObjectId

    oid = ObjectId(extraction_id)
    completed_doc["_id"] = oid
    mock_col.return_value.find_one.return_value = completed_doc
    mock_col.return_value.update_one.return_value = MagicMock()

    with patch("app.routes.extractions.template_storage_dir", return_value=tmp_path):
        with FIXTURE_XML.open("rb") as handle:
            response = client.post(
                f"/api/extractions/{extraction_id}/template",
                files={"file": ("1458242.xml", handle, "application/xml")},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == extraction_id
    assert data["template_id"]
    assert data["original_filename"] == "1458242.xml"
    assert data["schema"]["root_tag"] == "article"
    mock_col.return_value.update_one.assert_called_once()


@patch("app.routes.extractions.extractions_col")
def test_template_upload_invalid_xml(
    mock_col: MagicMock,
    extraction_id: str,
    completed_doc: dict,
    tmp_path: Path,
) -> None:
    from bson import ObjectId

    oid = ObjectId(extraction_id)
    completed_doc["_id"] = oid
    mock_col.return_value.find_one.return_value = completed_doc

    with patch("app.routes.extractions.template_storage_dir", return_value=tmp_path):
        response = client.post(
            f"/api/extractions/{extraction_id}/template",
            files={"file": ("bad.xml", b"<article><unclosed>", "application/xml")},
        )

    assert response.status_code == 400
    assert "Invalid XML" in response.json()["detail"]

