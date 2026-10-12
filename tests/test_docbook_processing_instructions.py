"""DocBook template processing instruction preservation."""

from __future__ import annotations

from lxml import etree

from app.services.docbook_body_merge import apply_pdf_body_to_docbook_book
from app.services.docbook_generator import generate_docbook_book_xml
from app.services.docbook_metadata_overlay import apply_pdf_metadata_to_docbook_book
from app.services.template_format import DOCBOOK_NS
from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.source_identity import SourceIdentityRecord
from app.utils.docbook_processing_instructions import (
    restore_processing_instructions,
    snapshot_processing_instructions,
)


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def test_snapshot_and_restore_page_pis_between_elements() -> None:
    xml = f"""<book xmlns="http://docbook.org/ns/docbook">
  <preface>
    <info><title>Prelims</title></info>
    <?page value="ii"?>
    <?page value="iii"?>
  </preface>
</book>"""
    root = _parse(xml)
    snap = snapshot_processing_instructions(root)
    for pi in list(root.findall(".//")):
        pass
    preface = root.find(f"{{{DOCBOOK_NS}}}preface")
    assert preface is not None
    for child in list(preface):
        if child.tag is etree.ProcessingInstruction:
            preface.remove(child)
    restore_processing_instructions(root, snap)
    pis = [c for c in preface if c.tag is etree.ProcessingInstruction]
    assert len(pis) == 2
    assert pis[0].target == "page"
    assert (pis[0].text or "").strip() == 'value="ii"'


def test_title_update_preserves_leading_page_pi() -> None:
    xml = f"""<book xmlns="http://docbook.org/ns/docbook"><info>
      <title><?page value="i"?>Old Title</title>
    </info></book>"""
    root = _parse(xml)
    title = root.find(f".//{{{DOCBOOK_NS}}}title")
    from app.services.docbook_metadata_overlay import _set_text

    _set_text(title, "New Title")
    pis = [c for c in title if c.tag is etree.ProcessingInstruction]
    assert len(pis) == 1
    assert pis[0].target == "page"
    assert (pis[0].tail or "").strip() == "New Title"


def test_restore_skips_mainmatter_chapter_pis() -> None:
    xml = f"""<book xmlns="http://docbook.org/ns/docbook">
  <chapter><para>Body</para><?page value="99"?></chapter>
</book>"""
    root = _parse(xml)
    snap = snapshot_processing_instructions(root)
    chapter = root.find(f"{{{DOCBOOK_NS}}}chapter")
    for child in list(chapter):
        if child.tag is etree.ProcessingInstruction:
            chapter.remove(child)
    restore_processing_instructions(root, snap)
    assert not any(c.tag is etree.ProcessingInstruction for c in chapter)


def test_body_merge_drops_template_front_matter_and_uses_pdf(tmp_path) -> None:
    template = tmp_path / "t.xml"
    template.write_text(
        f"""<book xmlns="http://docbook.org/ns/docbook">
  <info><title>Template</title></info>
  <part role="front"><preface><?page value="ii"?></preface></part>
  <chapter><title>Old</title><para>Remove.</para></chapter>
</book>""",
        encoding="utf-8",
    )
    tree = etree.parse(str(template))
    root = tree.getroot()
    mapping = SemanticMappingBody(
        body=[
            MappedSemanticNode(
                semantic_type="heading",
                text="PDF Chapter",
                metadata={"level": 1},
                children=[MappedSemanticNode(semantic_type="paragraph", text="From PDF.")],
            )
        ]
    )
    apply_pdf_body_to_docbook_book(root, mapping)
    assert root.find(f"{{{DOCBOOK_NS}}}part[@role='front']") is None
    assert root.find(f"{{{DOCBOOK_NS}}}chapter") is not None
    assert "From PDF" in etree.tostring(root, encoding="unicode")
    assert "Remove." not in etree.tostring(root, encoding="unicode")
