"""Build a minimal DocBook 5.0 <book> template from Phase 1 extraction metadata only."""

from __future__ import annotations

from typing import Any

from lxml import etree

from app.services.template_format import DOCBOOK_NS
from app.utils.docbook_xml_ids import apply_docbook_book_root_attributes
from app.utils.xml_serializer import serialize_lxml_tree


def build_docbook_template_xml_from_phase1(phase1: dict[str, Any]) -> str:
    """
    Create a new book skeleton from the current PDF extraction (no prior template content).

    Structure only — chapter bodies are placeholders until PDF merge exists.
    """
    title = (phase1.get("title") or "").strip() or None
    authors: list[str] = [str(a).strip() for a in (phase1.get("authors") or []) if str(a).strip()]
    publisher = (phase1.get("publisher") or "").strip() or None
    year = phase1.get("publication_year")
    isbn = (phase1.get("isbn") or "").strip() or None

    book = etree.Element(
        f"{{{DOCBOOK_NS}}}book",
        nsmap={None: DOCBOOK_NS},
    )
    apply_docbook_book_root_attributes(book)
    info = etree.SubElement(book, f"{{{DOCBOOK_NS}}}info")
    if title:
        title_el = etree.SubElement(info, f"{{{DOCBOOK_NS}}}title")
        title_el.text = title
    if authors:
        authorgroup = etree.SubElement(info, f"{{{DOCBOOK_NS}}}authorgroup")
        for name in authors:
            author = etree.SubElement(authorgroup, f"{{{DOCBOOK_NS}}}author")
            personname = etree.SubElement(author, f"{{{DOCBOOK_NS}}}personname")
            parts = name.split()
            if len(parts) >= 2:
                first = etree.SubElement(personname, f"{{{DOCBOOK_NS}}}firstname")
                first.text = parts[0]
                surname = etree.SubElement(personname, f"{{{DOCBOOK_NS}}}surname")
                surname.text = " ".join(parts[1:])
            else:
                surname = etree.SubElement(personname, f"{{{DOCBOOK_NS}}}surname")
                surname.text = name
    if publisher:
        biblioset = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioset", role="publisher")
        pub = etree.SubElement(biblioset, f"{{{DOCBOOK_NS}}}publisher")
        pubname = etree.SubElement(pub, f"{{{DOCBOOK_NS}}}publishername")
        pubname.text = publisher
    if year:
        copyright_el = etree.SubElement(info, f"{{{DOCBOOK_NS}}}copyright")
        year_el = etree.SubElement(copyright_el, f"{{{DOCBOOK_NS}}}year")
        year_el.text = str(year)
    if isbn:
        biblioid = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioid", attrib={"class": "isbn"})
        biblioid.text = isbn

    chapter = etree.SubElement(book, f"{{{DOCBOOK_NS}}}chapter")
    ch_title = etree.SubElement(chapter, f"{{{DOCBOOK_NS}}}title")
    ch_title.text = "Body"
    para = etree.SubElement(chapter, f"{{{DOCBOOK_NS}}}para")
    para.text = (
        "Placeholder chapter generated from the uploaded PDF metadata. "
        "Replace with publisher template XML or chapter merge when available."
    )

    return serialize_lxml_tree(
        book,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=None,
    )
