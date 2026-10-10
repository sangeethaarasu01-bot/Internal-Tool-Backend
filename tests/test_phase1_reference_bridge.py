"""Phase 1 bibliography → JATS ref-list via IR adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from app.services.ir_semantic_adapter import fill_back_references_from_ir, ir_to_semantic_mapping
from app.services.phase1_reference_bridge import merge_phase1_references_into_ir, phase1_references_to_ir_nodes
from app.services.xml_generator import generate_jats_xml

ROOT = Path(__file__).resolve().parent.parent
KAKICHI_PHASE1 = ROOT / "data" / "pipeline_debug" / "access-kakichi-3657695-proof.pdf1.pdf" / "phase1_document.json"
AMARA_TEMPLATE = ROOT / "data" / "outputs" / "tce-amarakorba-3658363-proof.pdf1.xml"


@pytest.mark.skipif(not KAKICHI_PHASE1.is_file(), reason="Kakichi phase1 fixture missing")
def test_phase1_references_bridge_populates_ir_and_xml() -> None:
    phase1 = json.loads(KAKICHI_PHASE1.read_text(encoding="utf-8"))
    nodes = phase1_references_to_ir_nodes(phase1)
    assert len(nodes) >= 20
    assert nodes[0]["type"] == "reference"
    assert nodes[0]["label"] == "[1]" or "[1]" in (nodes[0].get("text") or "")

    ir = {"front": {}, "body": {"sections": [], "loose_paragraphs": []}, "back": {"references": []}}
    merged = merge_phase1_references_into_ir(ir, phase1)
    assert len(merged["back"]["references"]) == len(nodes)

    mapping = ir_to_semantic_mapping(merged)
    mapping = fill_back_references_from_ir(mapping, merged)
    assert len(mapping.back.get("references") or []) >= 20

    if not AMARA_TEMPLATE.is_file():
        pytest.skip("template missing")
    xml = generate_jats_xml(AMARA_TEMPLATE, mapping)
    root = etree.fromstring(xml.encode("utf-8"))
    refs = root.xpath("//*[local-name()='ref-list']/*[local-name()='ref']")
    assert len(refs) >= 20
    assert refs[0].findtext("{*}label") or refs[0].findtext("label")
