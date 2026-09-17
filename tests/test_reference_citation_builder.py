"""Tests for structured IEEE JATS mixed-citation generation."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.xml_generator import generate_jats_xml
from app.utils.reference_citation_builder import populate_structured_mixed_citation

FIXTURE_TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "1458242.xml"

WHO_REF = (
    "World Health Organization. Breast Cancer: Prevention and Control. "
    "Accessed: Mar. 16, 2024. [Online]. Available: "
    "https://www.who.int/news-room/fact-sheets/detail/breast-cancer"
)

JOURNAL_REF = (
    "H. Sung, J. Ferlay, R. L. Siegel, M. Laversanne, I. Soerjomataram, A. Jemal, and F. Bray, "
    '"Global cancer statistics 2020: GLOBOCAN estimates of incidence and mortality worldwide '
    'for 36 cancers in 185 countries," CA: Cancer J. Clinicians, vol. 71, no. 3, pp. 209-249, '
    "May 2021."
)


def _citation_xml(text: str) -> etree._Element:
    citation = etree.Element("mixed-citation")
    populate_structured_mixed_citation(citation, text)
    return citation


def test_online_reference_uses_collab_source_uri() -> None:
    citation = _citation_xml(WHO_REF)
    assert citation.get("publication-type") == "book"
    assert citation.get("publication-format") == "online"
    assert citation.findtext("collab") == "World Health Organization"
    assert "Breast Cancer" in (citation.findtext("source") or "")
    assert citation.findtext("month") == "Mar."
    assert citation.findtext("day") == "16"
    assert citation.findtext("year") == "2024"
    assert citation.findtext("uri", "").startswith("https://www.who.int/")


def test_periodical_reference_uses_person_group_and_article_title() -> None:
    citation = _citation_xml(JOURNAL_REF)
    assert citation.get("publication-type") == "periodical"
    group = citation.find("person-group")
    assert group is not None
    names = group.findall("string-name")
    assert len(names) >= 2
    assert names[0].findtext("surname") == "Sung"
    assert "Global cancer statistics 2020" in (citation.findtext("article-title") or "")
    assert citation.findtext("volume") == "71"
    assert citation.findtext("issue") == "3"
    assert citation.findtext("fpage") == "209"
    assert citation.findtext("lpage") == "249"


def test_generate_jats_xml_back_matter_ref_list_structure(tmp_path: Path) -> None:
    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
  <back>
    <ack><title>Acknowledgment</title><p>Thanks.</p></ack>
    <ref-list><title>References</title></ref-list>
    <bio-group><bio id="bio1"><p>Bio</p></bio></bio-group>
  </back>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[],
        back={
            "references": [
                MappedSemanticNode(
                    semantic_type="reference",
                    label="[1]",
                    text=f"[1] {WHO_REF}",
                    source_block_ids=["p8_b1"],
                ),
                MappedSemanticNode(
                    semantic_type="reference",
                    label="[2]",
                    text=f"[2] {JOURNAL_REF}",
                    source_block_ids=["p8_b2"],
                ),
            ]
        },
    )
    xml = generate_jats_xml(template, mapping)
    assert "<ack>" in xml
    assert "<bio-group>" in xml
    assert "<ref-list>" in xml
    assert "<title>References</title>" in xml.replace(" ", "")
    assert '<ref id="ref1">' in xml
    assert '<ref id="ref2">' in xml
    assert "<collab>World Health Organization</collab>" in xml
    assert "<person-group" in xml
    assert "<article-title>" in xml
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in xml

    document = etree.fromstring(xml.encode("utf-8"))
    refs = document.findall(".//ref-list/ref")
    assert len(refs) == 2
    assert refs[0].findtext("label") == "[1]"
    assert refs[0].find("mixed-citation/collab") is not None


def test_template_refs_preserved_when_mapping_has_no_references() -> None:
    mapping = SemanticMappingBody(front={}, body=[], back={})
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert "<ref id=" in xml
    assert "<mixed-citation>" in xml
