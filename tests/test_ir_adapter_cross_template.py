"""IR adapter must emit current PDF content, not sample template publication text."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from lxml import etree

from app.services.extraction_workflow import apply_scope_to_extraction
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.text_extractor import extract_text_layout
from app.services.template_parser import TemplateParser
from app.services.xml_generator import generate_jats_xml

ROOT = Path(__file__).resolve().parent.parent
KAKICHI_PDF = ROOT / "data" / "pipeline_debug" / "access-kakichi-3657695-proof.pdf1.pdf" / "original.pdf"
AMARA_TEMPLATE = ROOT / "data" / "outputs" / "tce-amarakorba-3658363-proof.pdf1.xml"
KAKICHI_TITLE_FRAGMENT = "Real-Time Capable Optimal Energy Management"
AMARA_TITLE_FRAGMENT = "Split Multi-Task Federated Learning"


def _kakichi_filtered_ir() -> dict:
    if not KAKICHI_PDF.is_file():
        pytest.skip("Kakichi PDF fixture missing")
    raw = extract_text_layout(str(KAKICHI_PDF))
    full = build_full_extraction_result(raw, include_tagged_output=False)
    result_payload = full.model_dump()
    if not AMARA_TEMPLATE.is_file():
        pytest.skip("Amara template fixture missing")
    schema = TemplateParser(AMARA_TEMPLATE).parse().model_dump(mode="json")
    scoped = apply_scope_to_extraction(
        scope="full",
        result=result_payload,
        template_schema=schema,
    )
    return scoped["filtered_ir"]


@pytest.mark.slow
def test_kakichi_ir_with_amara_template_xml_title_from_pdf() -> None:
    filtered_ir = _kakichi_filtered_ir()
    title_el = (filtered_ir.get("front") or {}).get("title") or {}
    title_text = title_el.get("text") or ""
    if not title_text:
        for item in title_el.get("elements") or []:
            title_text += str(item.get("value") or "")
    assert KAKICHI_TITLE_FRAGMENT in title_text

    mapping = ir_to_semantic_mapping(filtered_ir)
    template_bytes_before = AMARA_TEMPLATE.read_bytes()
    xml = generate_jats_xml(AMARA_TEMPLATE, mapping)
    assert AMARA_TEMPLATE.read_bytes() == template_bytes_before

    root = etree.fromstring(xml.encode("utf-8"))
    article_titles = root.xpath(
        "//*[local-name()='article-meta']/*[local-name()='title-group']"
        "/*[local-name()='article-title']/text()"
    )
    merged_title = " ".join(t.strip() for t in article_titles if t and t.strip())
    assert KAKICHI_TITLE_FRAGMENT in merged_title
    assert AMARA_TITLE_FRAGMENT not in merged_title

    body_text = etree.tostring(
        root.find(".//{*}body") or root.find("body"),
        encoding="unicode",
        method="text",
    )
    assert "wheel loader" in body_text.lower() or "hybrid" in body_text.lower()
    assert "federated learning" not in body_text.lower()[:5000]


def test_stale_llm_cache_not_used_when_building_mapping_from_ir() -> None:
    """Regression: no-LLM path must not reuse semantic_mapping from another template run."""
    ir_a = {
        "front": {
            "title": {
                "type": "title",
                "elements": [{"type": "text", "value": "Paper A Title"}],
            }
        },
        "body": {
            "sections": [
                {
                    "heading": "Intro",
                    "level": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "elements": [{"type": "text", "value": "Content from paper A."}],
                        }
                    ],
                    "subsections": [],
                }
            ],
            "loose_paragraphs": [],
        },
        "back": {},
    }
    ir_b = copy.deepcopy(ir_a)
    ir_b["front"]["title"]["elements"][0]["value"] = "Paper B Title"
    ir_b["body"]["sections"][0]["content"][0]["elements"][0]["value"] = "Content from paper B."

    map_a = ir_to_semantic_mapping(ir_a)
    map_b = ir_to_semantic_mapping(ir_b)
    assert "Paper A" in _text_of_mapping_front(map_a)
    assert "Paper B" in _text_of_mapping_front(map_b)
    assert "Paper A" not in _text_of_mapping_front(map_b)


def _text_of_mapping_front(mapping) -> str:
    title = (mapping.front or {}).get("title") or {}
    return str(title.get("text") or title.get("elements", [{}])[0].get("value", ""))
