"""TIT proof PDF: author-query cover must not become journal-meta; TIT IDs from registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from app.models.semantic_mapping import SemanticMappingBody
from app.services.jats_metadata_overlay import build_jats_metadata_overlay
from app.services.journal_metadata_resolver import collect_journal_evidence, resolve_journal_metadata
from app.services.xml_generator import generate_jats_xml
from app.utils.proof_pdf import article_lead_text_from_phase1

ROOT = Path(__file__).resolve().parent.parent

ACCESS_TEMPLATE_SNIPPET = """<?xml version="1.0"?>
<article>
  <front>
    <journal-meta>
      <journal-id journal-id-type="ieee">0063500</journal-id>
      <journal-id journal-id-type="acronym">ACCESS</journal-id>
      <journal-id journal-id-type="coden">IAECCG</journal-id>
      <journal-title-group><journal-title>IEEE Access</journal-title></journal-title-group>
    </journal-meta>
    <article-meta/>
  </front>
  <body/>
  <back/>
</article>"""

TIT_ARTICLE_PAGE = (
    "IEEE TRANSACTIONS ON INFORMATION THEORY\n"
    "VOLUME 72, 2026\n"
    "Manuscript ID TIT-2025-04-56245\n"
    "Digital Object Identifier 10.1109/TIT.2026.3658855\n"
    "Improving Wald's (Approximate) Sequential Probability Ratio Test by Avoiding Overshoot\n"
    "Lasse Fischer and Aaditya Ramdas\n"
    "Received 11 June 2025; revised 16 January 2026; accepted 20 January 2026\n"
    "ABSTRACT\n"
    "This paper studies sequential testing.\n"
    "Index Terms—Sequential analysis, hypothesis testing.\n"
)

AUTHOR_QUERIES_PAGE = (
    "AUTHOR QUERIES\n"
    "AUTHOR PLEASE ANSWER ALL QUERIES\n"
    "AQ: 1 Please confirm author names.\n"
    "AQ: 2 Upload corrections via Author Gateway.\n"
)

TIT_PHASE1 = {
    "source_filename": "tit-fischer-3658855-proof.pdf1.pdf",
    "pages": [
        {"raw_page_text": AUTHOR_QUERIES_PAGE},
        {"raw_page_text": TIT_ARTICLE_PAGE},
    ],
}

_CANDIDATE_PDFS = [
    ROOT / "uploads" / "tit-fischer-3658855-proof.pdf1.pdf",
    ROOT.parent / "tit-fischer-3658855-proof.pdf1.pdf",
    ROOT / "data" / "pipeline_debug" / "tit-fischer-3658855-proof.pdf1.pdf" / "original.pdf",
]


def _find_tit_pdf() -> Path | None:
    for path in _CANDIDATE_PDFS:
        if path.is_file():
            return path
    return None


def test_article_lead_text_skips_author_queries_page() -> None:
    lead = article_lead_text_from_phase1(TIT_PHASE1)
    assert "AUTHOR QUERIES" not in lead.upper()
    assert "INFORMATION THEORY" in lead.upper()


def test_journal_evidence_not_author_queries() -> None:
    lead = article_lead_text_from_phase1(TIT_PHASE1)
    evidence = collect_journal_evidence(
        header_text=lead,
        ir={"front": {"journal_header": {"text": "AUTHOR QUERIES", "elements": []}}},
        source_filename=TIT_PHASE1["source_filename"],
    )
    resolution = resolve_journal_metadata(evidence)
    assert resolution.journal is not None
    assert resolution.journal.acronym == "TIT"
    assert "AUTHOR" not in (resolution.journal_title or "").upper()


def test_tit_overlay_with_access_template(tmp_path: Path) -> None:
    template = tmp_path / "access.xml"
    template.write_text(ACCESS_TEMPLATE_SNIPPET, encoding="utf-8")
    xml = generate_jats_xml(
        template,
        SemanticMappingBody(),
        phase1=TIT_PHASE1,
        source_filename=TIT_PHASE1["source_filename"],
    )
    root = etree.fromstring(xml.encode("utf-8"))
    journal_title = root.xpath(
        "string(//*[local-name()='journal-meta']"
        "/*[local-name()='journal-title-group']/*[local-name()='journal-title'])"
    )
    assert "AUTHOR QUERIES" not in journal_title.upper()
    assert "INFORMATION THEORY" in journal_title.upper()
    assert (
        root.xpath(
            "string(//*[local-name()='journal-id'][@journal-id-type='ieee'])"
        )
        == "0047800"
    )
    assert (
        root.xpath(
            "string(//*[local-name()='journal-id'][@journal-id-type='acronym'])"
        )
        == "TIT"
    )
    assert (
        root.xpath(
            "string(//*[local-name()='journal-id'][@journal-id-type='coden'])"
        )
        == "IETTAW"
    )
    doi = root.xpath("string(//*[local-name()='article-id'][@pub-id-type='doi'])")
    assert doi == "10.1109/TIT.2026.3658855"
    manuscript = root.xpath("string(//*[local-name()='article-id'][@pub-id-type='manuscript'])")
    assert manuscript == "TIT-2025-04-56245"


def test_build_overlay_extracts_history_dates(tmp_path: Path) -> None:
    overlay = build_jats_metadata_overlay(
        phase1=TIT_PHASE1,
        ir={},
        mapping=SemanticMappingBody(),
        source_filename=TIT_PHASE1["source_filename"],
    )
    assert overlay.journal is not None
    assert overlay.journal.acronym == "TIT"
    assert overlay.doi == "10.1109/TIT.2026.3658855"

    template = tmp_path / "access.xml"
    template.write_text(
        ACCESS_TEMPLATE_SNIPPET.replace("<article-meta/>", "<article-meta><history/></article-meta>"),
        encoding="utf-8",
    )
    xml = generate_jats_xml(
        template,
        SemanticMappingBody(),
        phase1=TIT_PHASE1,
        source_filename=TIT_PHASE1["source_filename"],
    )
    assert "11 June 2025" in xml
    assert "20 January 2026" in xml


def test_article_starts_page_one_without_proof_cover(tmp_path: Path) -> None:
    template = tmp_path / "access.xml"
    template.write_text(ACCESS_TEMPLATE_SNIPPET, encoding="utf-8")
    phase1 = {
        "source_filename": "tit-fischer-3658855-proof.pdf1.pdf",
        "pages": [{"raw_page_text": TIT_ARTICLE_PAGE}],
    }
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1)
    assert "TIT" in xml
    assert "AUTHOR QUERIES" not in xml.upper()


@pytest.mark.slow
def test_tit_pdf_integration_when_fixture_present() -> None:
    pdf = _find_tit_pdf()
    if pdf is None:
        pytest.skip("tit-fischer PDF not on disk")
    from app.services.extraction_workflow import apply_scope_to_extraction
    from app.services.layout.document_pipeline import build_full_extraction_result
    from app.services.text_extractor import extract_text_layout

    raw = extract_text_layout(str(pdf))
    full = build_full_extraction_result(raw, include_tagged_output=False)
    lead = article_lead_text_from_phase1(full.model_dump().get("phase1") or {})
    if not lead:
        phase1 = {"pages": [{"raw_page_text": "\n".join(b.text for p in raw.pages for b in p.blocks)}]}
        lead = article_lead_text_from_phase1(phase1)
    assert "AUTHOR QUERIES" not in lead[:500].upper() or "INFORMATION THEORY" in lead.upper()
