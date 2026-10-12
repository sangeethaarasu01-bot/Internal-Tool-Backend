"""Journal metadata resolution: PDF-first, registry-backed, template-safe."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.constants.ieee_journals import lookup_ieee_journal
from app.models.semantic_mapping import SemanticMappingBody
from app.services.jats_metadata_overlay import build_jats_metadata_overlay
from app.services.journal_metadata_resolver import (
    collect_journal_evidence,
    resolve_journal_metadata,
)
from app.services.xml_generator import generate_jats_xml

ROOT = Path(__file__).resolve().parent.parent
ACCESS_TEMPLATE_SNIPPET = """<?xml version="1.0"?>
<article>
  <front>
    <journal-meta>
      <journal-id journal-id-type="ieee">0063500</journal-id>
      <journal-id journal-id-type="acronym">ACCESS</journal-id>
      <journal-id journal-id-type="coden">IAECCG</journal-id>
      <journal-title-group><journal-title>IEEE Access</journal-title></journal-title-group>
      <issn publication-format="print">2169-3536</issn>
    </journal-meta>
    <article-meta/>
  </front>
  <body/>
  <back><ref-list><title>References</title></ref-list></back>
</article>"""


def _write_access_template(tmp_path: Path) -> Path:
    path = tmp_path / "access_template.xml"
    path.write_text(ACCESS_TEMPLATE_SNIPPET, encoding="utf-8")
    return path


def _journal_ids(xml: str) -> dict[str, str]:
    root = etree.fromstring(xml.encode("utf-8"))
    journal_meta = root.xpath("//*[local-name()='journal-meta']")[0]
    ids: dict[str, str] = {}
    for node in journal_meta.xpath("*[local-name()='journal-id']"):
        ids[node.get("journal-id-type")] = (node.text or "").strip()
    return ids


def test_access_pdf_with_access_template_keeps_access_metadata(tmp_path: Path) -> None:
    template = _write_access_template(tmp_path)
    phase1 = {
        "source_filename": "access-kakichi-3657695-proof.pdf1.pdf",
        "pages": [{"raw_page_text": "IEEE Access\n10.1109/ACCESS.2026.3657695\n"}],
    }
    overlay = build_jats_metadata_overlay(phase1=phase1, ir={}, mapping=SemanticMappingBody())
    assert overlay.journal is not None
    assert overlay.journal.acronym == "ACCESS"
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1, source_filename=phase1["source_filename"])
    ids = _journal_ids(xml)
    assert ids["ieee"] == "0063500"
    assert ids["acronym"] == "ACCESS"
    assert ids["coden"] == "IAECCG"


def test_jssc_pdf_with_access_template_overrides_to_jssc(tmp_path: Path) -> None:
    template = _write_access_template(tmp_path)
    phase1 = {
        "source_filename": "jssc-qin-3657757-proof.pdf1.pdf",
        "pages": [
            {
                "raw_page_text": (
                    "IEEE JOURNAL OF SOLID-STATE CIRCUITS\n"
                    "Digital Object Identifier 10.1109/JSSC.2026.3657757\n"
                )
            }
        ],
    }
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1, source_filename=phase1["source_filename"])
    ids = _journal_ids(xml)
    assert ids["ieee"] == "0055700"
    assert ids["acronym"] == "JSSC"
    assert ids["coden"] == "IJSCBC"


def test_tce_pdf_with_access_template_resolves_tce(tmp_path: Path) -> None:
    template = _write_access_template(tmp_path)
    phase1 = {
        "source_filename": "tce-amarakorba-3658363-proof.pdf1.pdf",
        "pages": [{"raw_page_text": "IEEE Transactions on Consumer Electronics\n10.1109/TCE.2026.3658363\n"}],
    }
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1, source_filename=phase1["source_filename"])
    ids = _journal_ids(xml)
    assert ids["acronym"] == "TCE"
    assert ids["ieee"] == "0074700"


def test_access_pdf_with_jssc_template_still_uses_access(tmp_path: Path) -> None:
    jssc_template = tmp_path / "jssc_template.xml"
    jssc_template.write_text(
        ACCESS_TEMPLATE_SNIPPET.replace("0063500", "0055700")
        .replace("ACCESS", "JSSC")
        .replace("IAECCG", "IJSCBC")
        .replace("IEEE Access", "IEEE Journal of Solid-State Circuits"),
        encoding="utf-8",
    )
    phase1 = {
        "source_filename": "access-kakichi-3657695-proof.pdf1.pdf",
        "pages": [{"raw_page_text": "IEEE Access\n10.1109/ACCESS.2026.3657695\n"}],
    }
    xml = generate_jats_xml(jssc_template, SemanticMappingBody(), phase1=phase1, source_filename=phase1["source_filename"])
    ids = _journal_ids(xml)
    assert ids["acronym"] == "ACCESS"
    assert ids["ieee"] == "0063500"


def test_unknown_journal_does_not_keep_template_ieee_ids(tmp_path: Path) -> None:
    template = _write_access_template(tmp_path)
    phase1 = {
        "source_filename": "mystery-paper-1234567-proof.pdf1.pdf",
        "pages": [{"raw_page_text": "Journal of Imaginary Engineering\nABSTRACT\nBody text."}],
    }
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1, source_filename=phase1["source_filename"])
    ids = _journal_ids(xml)
    assert "ieee" not in ids
    assert "coden" not in ids
    assert "Imaginary Engineering" in xml


def test_pdf_title_beats_conflicting_filename_prefix() -> None:
    header = "IEEE JOURNAL OF SOLID-STATE CIRCUITS\n10.1109/JSSC.2026.3657757\n"
    evidence = collect_journal_evidence(
        header_text=header,
        ir={},
        source_filename="tce-wrong-prefix-3657757-proof.pdf1.pdf",
    )
    resolution = resolve_journal_metadata(evidence)
    assert resolution.journal is not None
    assert resolution.journal.acronym == "JSSC"


def test_filename_prefix_when_pdf_title_missing() -> None:
    evidence = collect_journal_evidence(
        header_text="ABSTRACT\nSome paper text.",
        ir={},
        source_filename="tce-amarakorba-3658363-proof.pdf1.pdf",
    )
    resolution = resolve_journal_metadata(evidence)
    assert resolution.journal is not None
    assert resolution.journal.acronym == "TCE"


def test_heuristic_generate_xml_without_llm_key(tmp_path: Path) -> None:
    """generate_jats_xml path is the shared heuristic resolver (no LLM)."""
    template = _write_access_template(tmp_path)
    phase1 = {"pages": [{"raw_page_text": "IEEE Access\n"}], "source_filename": "access-demo-proof.pdf1.pdf"}
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1)
    assert _journal_ids(xml)["acronym"] == "ACCESS"


def test_llm_mapping_uses_same_overlay_builder() -> None:
    """LLM mode still ends in generate_jats_xml; overlay builder is shared."""
    phase1 = {"pages": [{"raw_page_text": "IEEE Access\n10.1109/ACCESS.2026.1111111\n"}]}
    overlay = build_jats_metadata_overlay(phase1=phase1, ir={}, mapping=SemanticMappingBody())
    assert overlay.journal is not None
    assert overlay.journal.acronym == "ACCESS"


def test_body_content_unchanged_by_journal_overlay(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode

    template = _write_access_template(tmp_path)
    mapping = SemanticMappingBody(
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="Unique body marker journal-meta-test-xyzzy.",
            )
        ]
    )
    phase1 = {
        "source_filename": "jssc-qin-3657757-proof.pdf1.pdf",
        "pages": [{"raw_page_text": "IEEE JOURNAL OF SOLID-STATE CIRCUITS\n"}],
    }
    xml = generate_jats_xml(template, mapping, phase1=phase1, source_filename=phase1["source_filename"])
    assert "journal-meta-test-xyzzy" in xml
    assert _journal_ids(xml)["acronym"] == "JSSC"


def test_lookup_jssc_from_title() -> None:
    journal = lookup_ieee_journal(journal_title="IEEE JOURNAL OF SOLID-STATE CIRCUITS")
    assert journal is not None
    assert journal.ieee_id == "0055700"
