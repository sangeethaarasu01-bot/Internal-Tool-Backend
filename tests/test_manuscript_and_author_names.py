"""Manuscript article-id extraction and JATS author name fields."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.jats_metadata_overlay import _infer_manuscript_id, build_jats_metadata_overlay
from app.services.xml_generator import generate_jats_xml
from app.utils.person_name import split_person_name

ACCESS_TEMPLATE = """<?xml version="1.0"?>
<article><front><journal-meta/><article-meta>
  <article-id pub-id-type="manuscript">ACCESS-2025-56245</article-id>
  <contrib-group/>
</article-meta></front><body/><back/></article>"""


def test_explicit_manuscript_id_extracted_from_pdf_header() -> None:
    header = (
        "IEEE TRANSACTIONS ON INFORMATION THEORY\n"
        "Manuscript ID TIT-2025-04-56245\n"
        "10.1109/TIT.2026.3658855\n"
    )
    ms = _infer_manuscript_id(header, "tit-fischer-3658855-proof.pdf1.pdf", "3658855", journal=None)
    assert ms == "TIT-2025-04-56245"


def test_template_manuscript_not_copied_when_source_missing(tmp_path: Path) -> None:
    template = tmp_path / "t.xml"
    template.write_text(ACCESS_TEMPLATE, encoding="utf-8")
    phase1 = {
        "pages": [{"raw_page_text": "IEEE Access\n10.1109/ACCESS.2026.1111111\n"}],
        "source_filename": "access-demo-proof.pdf1.pdf",
    }
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1)
    assert "ACCESS-2025-56245" not in xml
    root = etree.fromstring(xml.encode())
    manuscript_nodes = root.xpath(
        "//*[local-name()='article-id'][@pub-id-type='manuscript']"
    )
    assert not manuscript_nodes


def test_manuscript_inferred_from_journal_and_article_number_when_labeled_in_volume() -> None:
    header = "IEEE Access\nVOLUME 12, 2026\n"
    from app.constants.ieee_journals import lookup_ieee_journal

    journal = lookup_ieee_journal(journal_title="IEEE Access")
    ms = _infer_manuscript_id(
        header,
        "access-kakichi-3657695-proof.pdf1.pdf",
        "3657695",
        journal=journal,
        publication_year=2026,
    )
    assert ms == "ACCESS-2026-3657695"


def test_doi_unaffected_by_manuscript_handling(tmp_path: Path) -> None:
    template = tmp_path / "t.xml"
    template.write_text(ACCESS_TEMPLATE, encoding="utf-8")
    phase1 = {
        "pages": [{"raw_page_text": "IEEE Access\n10.1109/ACCESS.2026.2222222\n"}],
    }
    xml = generate_jats_xml(template, SemanticMappingBody(), phase1=phase1)
    assert "10.1109/ACCESS.2026.2222222" in xml


def test_split_person_name_variants() -> None:
    assert split_person_name("Lasse Fischer") == ("Lasse", "Fischer")
    assert split_person_name("Mary Jane Watson") == ("Mary Jane", "Watson")
    assert split_person_name("A. B. Smith") == ("A. B.", "Smith")
    assert split_person_name("Jan van der Berg") == ("Jan", "van der Berg")
    assert split_person_name("Madonna") == ("", "Madonna")


def test_author_given_names_and_surname_in_generated_xml(tmp_path: Path) -> None:
    template = tmp_path / "t.xml"
    template.write_text(ACCESS_TEMPLATE, encoding="utf-8")
    mapping = SemanticMappingBody(
        front={
            "authors": [
                MappedSemanticNode(semantic_type="author", text="Lasse Fischer").model_dump(
                    mode="json"
                ),
                MappedSemanticNode(semantic_type="author", text="Aaditya Ramdas").model_dump(
                    mode="json"
                ),
            ]
        }
    )
    xml = generate_jats_xml(template, mapping)
    root = etree.fromstring(xml.encode())
    surnames = "|".join(
        t.strip()
        for t in root.xpath("//*[local-name()='contrib']//*[local-name()='surname']/text()")
        if t and t.strip()
    )
    givens = "|".join(
        t.strip()
        for t in root.xpath("//*[local-name()='contrib']//*[local-name()='given-names']/text()")
        if t and t.strip()
    )
    assert "Fischer" in surnames
    assert "Ramdas" in surnames
    assert "Lasse" in givens
    assert "Aaditya" in givens
    assert surnames.index("Fischer") < surnames.index("Ramdas")


def test_tit_phase1_manuscript_overlay_warning_and_value() -> None:
    phase1 = {
        "source_filename": "tit-fischer-3658855-proof.pdf1.pdf",
        "pages": [
            {"raw_page_text": "AUTHOR QUERIES\n"},
            {
                "raw_page_text": (
                    "IEEE TRANSACTIONS ON INFORMATION THEORY\n"
                    "Manuscript ID TIT-2025-04-56245\n"
                    "10.1109/TIT.2026.3658855\n"
                )
            },
        ],
    }
    overlay = build_jats_metadata_overlay(
        phase1=phase1,
        ir={},
        mapping=SemanticMappingBody(),
        source_filename=phase1["source_filename"],
    )
    assert overlay.manuscript_id == "TIT-2025-04-56245"
    assert not any("manuscript_id_unavailable" in w for w in overlay.warnings)
