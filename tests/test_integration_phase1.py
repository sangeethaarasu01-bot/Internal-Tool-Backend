"""Phase 1 integration: PDF → IR → scope_resolver (real data, not mocked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.layout.document_pipeline import process_document_structure
from app.services.scope_resolver import resolve_scope
from app.services.template_parser import TemplateParser
from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
IEEE_PDF = ROOT / "uploads" / "20260907_132003_jsen-banerjeeroy-3639180-proof1.pdf"
FIXTURE_XML = ROOT / "tests" / "fixtures" / "1458242.xml"
KNOWN_TAGS = ROOT / "app" / "constants" / "jats_2_0_known_tags.json"


def _build_ir_from_pdf(pdf_path: Path) -> dict:
    raw = extract_text_layout(str(pdf_path))
    structure = process_document_structure(raw)
    assert structure.semantic is not None
    return structure.semantic.to_ir_json()


def _template_schema_dict() -> dict:
    schema = TemplateParser(FIXTURE_XML, known_tags_path=KNOWN_TAGS).parse()
    return schema.model_dump(mode="json")


def _count_front_nodes(front: dict) -> int:
    count = 0
    for value in front.values():
        if value is None:
            continue
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += 1
    return count


def _count_body_nodes(body: dict) -> int:
    count = len(body.get("loose_paragraphs", []))
    for section in body.get("sections", []):
        if section.get("heading_element"):
            count += 1
        count += len(section.get("paragraphs", []))
        count += len(section.get("content", []))
        for subsection in section.get("subsections", []):
            count += _count_body_nodes({"sections": [subsection], "loose_paragraphs": []})
    return count


def _count_back_nodes(back: dict) -> int:
    count = len(back.get("references", [])) + len(back.get("other", []))
    if back.get("reference_list"):
        count += 1
    return count


@pytest.fixture(scope="module")
def ir_json() -> dict:
    if not IEEE_PDF.exists():
        pytest.skip("IEEE proof PDF not in uploads")
    return _build_ir_from_pdf(IEEE_PDF)


@pytest.fixture(scope="module")
def template_schema() -> dict:
    return _template_schema_dict()


@pytest.mark.parametrize("scope", ["front", "back", "full"])
def test_pdf_to_ir_to_scope_chain(
    ir_json: dict,
    template_schema: dict,
    scope: str,
) -> None:
    source_front = _count_front_nodes(ir_json["front"])
    source_body = _count_body_nodes(ir_json["body"])
    source_back = _count_back_nodes(ir_json["back"])

    assert source_front + source_body + source_back > 0, "IR should contain content from real PDF"

    result = resolve_scope(scope, template_schema, ir_json)
    filtered = result["filtered_ir"]

    assert result["resolved_scope"] == scope
    assert "front" in filtered and "body" in filtered and "back" in filtered

    filtered_front = _count_front_nodes(filtered["front"])
    filtered_body = _count_body_nodes(filtered["body"])
    filtered_back = _count_back_nodes(filtered["back"])

    if scope == "front":
        assert filtered_front == source_front
        assert filtered_body == 0
        assert filtered_back == 0
        assert result["dropped_element_count"] > 0
    elif scope == "back":
        assert filtered_front == 0
        assert filtered_body == 0
        assert filtered_back == source_back
        assert result["dropped_element_count"] > 0
    else:
        assert filtered_front == source_front
        assert filtered_body == source_body
        assert filtered_back == source_back
        assert result["dropped_element_count"] == 0
