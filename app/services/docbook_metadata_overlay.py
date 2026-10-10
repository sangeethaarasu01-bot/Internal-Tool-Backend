"""Replace book-level publication metadata in a DocBook template with PDF extraction identity."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from lxml import etree

from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS
from app.utils.xml_helpers import iter_element_children, xml_local_name

logger = logging.getLogger(__name__)


def _direct_child(parent: etree._Element, local_name: str) -> etree._Element | None:
    for child in iter_element_children(parent):
        if xml_local_name(child) == local_name:
            return child
    return None


@dataclass
class DocBookMetadataOverlayResult:
    applied: bool = False
    warnings: list[str] = field(default_factory=list)


def _set_text(element: etree._Element, text: str) -> None:
    element.text = text
    for child in element:
        element.remove(child)


def _remove_publication_identifiers(info: etree._Element) -> None:
    for biblioid in list(info.iter(f"{{{DOCBOOK_NS}}}biblioid")):
        if biblioid.getparent() is None:
            continue
        kind = (biblioid.get("class") or "").lower()
        if kind in {"isbn", "doi", "isbn13", "isbn10"}:
            parent = biblioid.getparent()
            if parent is not None and xml_local_name(parent) == "info":
                parent.remove(biblioid)


def _set_or_create_title(info: etree._Element, title: str) -> None:
    title_el = _direct_child(info, "title")
    if title_el is None:
        title_el = etree.Element(f"{{{DOCBOOK_NS}}}title")
        info.insert(0, title_el)
    _set_text(title_el, title)


def _clear_subtitle(info: etree._Element) -> None:
    subtitle = _direct_child(info, "subtitle")
    if subtitle is not None:
        info.remove(subtitle)


def _replace_authorgroup(info: etree._Element, authors: list[str]) -> None:
    for child in list(iter_element_children(info)):
        if xml_local_name(child) == "authorgroup":
            info.remove(child)
    if not authors:
        return
    authorgroup = etree.Element(f"{{{DOCBOOK_NS}}}authorgroup")
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
    info.append(authorgroup)


def _update_publisher_name(info: etree._Element, publisher: str | None) -> None:
    if not publisher:
        return
    for biblioset in info.iter(f"{{{DOCBOOK_NS}}}biblioset"):
        if biblioset.get("role") not in {None, "publisher"}:
            continue
        for pub in biblioset.iter(f"{{{DOCBOOK_NS}}}publisher"):
            name_el = _direct_child(pub, "publishername")
            if name_el is not None:
                _set_text(name_el, publisher)
                return
        misc = biblioset.find(f".//{{{DOCBOOK_NS}}}bibliomisc[@role='imprint']")
        if misc is not None:
            _set_text(misc, publisher)
            return


def _update_copyright_year(info: etree._Element, year: int | None) -> None:
    if year is None:
        return
    copyright_el = _direct_child(info, "copyright")
    if copyright_el is None:
        copyright_el = etree.SubElement(info, f"{{{DOCBOOK_NS}}}copyright")
    year_el = _direct_child(copyright_el, "year")
    if year_el is None:
        year_el = etree.SubElement(copyright_el, f"{{{DOCBOOK_NS}}}year")
    _set_text(year_el, str(year))


def _update_pubdate(info: etree._Element, year: int | None) -> None:
    if year is None:
        return
    for pubdate in info.findall(f"{{{DOCBOOK_NS}}}pubdate"):
        _set_text(pubdate, str(year))


def _append_isbn(info: etree._Element, isbn: str | None) -> None:
    if not isbn:
        return
    biblioid = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioid", attrib={"class": "isbn"})
    biblioid.text = isbn.strip()


def apply_pdf_metadata_to_docbook_book(
    book: etree._Element,
    source: SourceIdentityRecord,
) -> DocBookMetadataOverlayResult:
    """
    Overwrite publication-specific fields in ``<book>/<info>`` using Phase 1 / PDF identity.

    Chapter bodies and structural elements are unchanged.
    """
    result = DocBookMetadataOverlayResult()
    info = _direct_child(book, "info")
    if info is None:
        if not source.title and not source.isbn and source.publication_year is None:
            result.warnings.append(
                "DocBook template has no <info> block and PDF metadata is sparse; "
                "output may retain template publication fields."
            )
            return result
        info = etree.SubElement(book, f"{{{DOCBOOK_NS}}}info")
        book.insert(0, info)

    has_any = bool(source.title or source.isbn or source.publication_year or source.authors)
    if not has_any:
        result.warnings.append(
            "PDF metadata (title/ISBN/year/authors) was not extracted reliably; "
            "book-level fields were not replaced."
        )
        return result

    _remove_publication_identifiers(info)
    if source.title:
        _set_or_create_title(info, source.title.strip())
        _clear_subtitle(info)
    if source.authors:
        _replace_authorgroup(info, list(source.authors))
    _update_publisher_name(info, source.publisher)
    _update_copyright_year(info, source.publication_year)
    _update_pubdate(info, source.publication_year)
    _append_isbn(info, source.isbn)

    result.applied = True
    logger.info(
        "docbook_metadata_overlay extraction_id=%s title=%s isbn=%s year=%s",
        source.extraction_id,
        (source.title or "-")[:80],
        source.isbn or "-",
        source.publication_year,
    )
    return result
