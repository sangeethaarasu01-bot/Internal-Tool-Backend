"""JATS fixes for cross-template Kakichi PDF + Amara template."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from app.services.ir_semantic_adapter import fill_back_references_from_ir, ir_to_semantic_mapping
from app.services.phase1_reference_bridge import merge_phase1_references_into_ir
from app.services.source_identity import build_source_identity_from_extraction_doc
from app.services.xml_generator import generate_jats_xml
from tests.test_ir_adapter_cross_template import _kakichi_filtered_ir

ROOT = Path(__file__).resolve().parent.parent
KAKICHI_DIR = ROOT / "data" / "pipeline_debug" / "access-kakichi-3657695-proof.pdf1.pdf"
KAKICHI_PHASE1 = KAKICHI_DIR / "phase1_document.json"
AMARA_TEMPLATE = ROOT / "data" / "outputs" / "tce-amarakorba-3658363-proof.pdf1.xml"


@pytest.mark.slow
@pytest.mark.skipif(not KAKICHI_PHASE1.is_file() or not AMARA_TEMPLATE.is_file(), reason="fixtures missing")
def test_kakichi_jats_metadata_sections_and_graphics() -> None:
    phase1 = json.loads(KAKICHI_PHASE1.read_text(encoding="utf-8"))
    merged_ir = merge_phase1_references_into_ir(_kakichi_filtered_ir(), phase1)
    mapping = fill_back_references_from_ir(ir_to_semantic_mapping(merged_ir), merged_ir)

    source = build_source_identity_from_extraction_doc(
        {
            "_id": "kakichi-test",
            "original_filename": phase1["source_filename"],
            "phase1": phase1,
            "page_count": len(phase1.get("pages") or []),
        }
    )
    xml = generate_jats_xml(
        AMARA_TEMPLATE,
        mapping,
        phase1=phase1,
        source_filename=phase1["source_filename"],
        ir=merged_ir,
        source=source,
    )
    root = etree.fromstring(xml.encode("utf-8"))

    sec_ids = root.xpath("//*[local-name()='body']//*[local-name()='sec']/@id")
    assert len(sec_ids) == len(set(sec_ids))
    assert "ACKNOWLEDGMENT" not in " ".join(
        t.strip().upper()
        for t in root.xpath("//*[local-name()='body']//*[local-name()='title']/text()")
        if t and t.strip()
    )

    journal_meta = root.xpath("//*[local-name()='journal-meta']")[0]
    journal = root.xpath(
        "string(//*[local-name()='journal-meta']/*[local-name()='journal-title-group']"
        "/*[local-name()='journal-title'])"
    )
    assert "Consumer Electronics" not in journal
    assert "IEEE Access" in journal
    assert journal_meta.xpath("string(*[local-name()='journal-id'][@journal-id-type='ieee'])") == "0063500"
    assert journal_meta.xpath("string(*[local-name()='journal-id'][@journal-id-type='acronym'])") == "ACCESS"
    assert journal_meta.xpath("string(*[local-name()='journal-id'][@journal-id-type='coden'])") == "IAECCG"
    assert journal_meta.xpath("string(*[local-name()='issn'][@publication-format='print'])") == "2169-3536"
    assert journal_meta.xpath("string(*[local-name()='issn'][@publication-format='online'])") == "2169-3536"

    doi = root.xpath("string(//*[local-name()='article-id'][@pub-id-type='doi'])")
    assert doi.startswith("10.1109/ACCESS.")
    assert "3658363" not in doi

    year = root.xpath("string(//*[local-name()='pub-date']/*[local-name()='year'])")
    assert year == "2026"

    history = root.xpath("//*[local-name()='history']/*[local-name()='date']")
    assert len(history) >= 2

    affs = root.xpath("//*[local-name()='article-meta']/*[local-name()='aff']")
    assert len(affs) >= 4

    fig_nodes = root.xpath("//*[local-name()='body']//*[local-name()='fig']")
    table_nodes = root.xpath("//*[local-name()='body']//*[local-name()='table-wrap']")
    equation_nodes = root.xpath("//*[local-name()='body']//*[local-name()='disp-formula']")
    assert root.xpath("string(//*[local-name()='fig-count']/@count)") == str(len(fig_nodes))
    assert root.xpath("string(//*[local-name()='table-count']/@count)") == str(len(table_nodes))
    assert root.xpath("string(//*[local-name()='equation-count']/@count)") == str(len(equation_nodes))
    assert len(fig_nodes) >= 20
    ref_nodes = root.xpath("//*[local-name()='ref-list']/*[local-name()='ref']")
    assert len(ref_nodes) >= 32
    assert root.xpath("string(//*[local-name()='ref-count']/@count)") == str(len(ref_nodes))
    assert root.xpath("string(//*[local-name()='page-count']/@count)") == "17"

    href = root.xpath("string(//*[local-name()='fig'][@id='fig1']/*[local-name()='graphic']/@*[local-name()='href'])")
    assert href == "kakichi1-3657695.eps"
    assert "amara" not in href.lower()

    ack = root.xpath("string(//*[local-name()='back']/*[local-name()='ack']//*[local-name()='p'])")
    assert "Yanmar" in ack

