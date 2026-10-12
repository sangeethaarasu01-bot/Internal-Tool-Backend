"""Replace book-level publication metadata in a DocBook template with PDF extraction identity."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from lxml import etree

from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS
from app.utils.docbook_sortas import apply_sortas_to_title_element
from app.utils.docbook_template_attrs import update_authorgroup_authors
from app.utils.xml_helpers import iter_element_children, xml_local_name
from app.utils.xml_text import sanitize_xml_text, set_lxml_text

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
    for child in element:
        element.remove(child)
    set_lxml_text(element, text, log_context={"semantic_type": "metadata", "source": "-", "field": "docbook"})


def _remove_publication_identifiers(info: etree._Element) -> None:
    for biblioset in list(info.findall(f"{{{DOCBOOK_NS}}}biblioset")):
        if (biblioset.get("role") or "").lower() == "isbns":
            info.remove(biblioset)
    for biblioid in list(info.iter(f"{{{DOCBOOK_NS}}}biblioid")):
        if biblioid.getparent() is None:
            continue
        kind = (biblioid.get("class") or "").lower()
        if kind in {"isbn", "doi", "isbn13", "isbn10"}:
            parent = biblioid.getparent()
            if parent is not None:
                parent.remove(biblioid)


def _set_or_create_title(info: etree._Element, title: str) -> None:
    title_el = _direct_child(info, "title")
    if title_el is None:
        title_el = etree.Element(f"{{{DOCBOOK_NS}}}title")
        info.insert(0, title_el)
    stripped = title.strip()
    _set_text(title_el, stripped)
    apply_sortas_to_title_element(title_el, stripped)


def _clear_subtitle(info: etree._Element) -> None:
    subtitle = _direct_child(info, "subtitle")
    if subtitle is not None:
        info.remove(subtitle)


def _replace_authorgroup(info: etree._Element, authors: list[str]) -> None:
    people = [name.strip() for name in authors if name.strip()]
    people = [name for name in people if not _looks_like_imprint_name(name)]
    if not people:
        for child in list(iter_element_children(info)):
            if xml_local_name(child) == "authorgroup":
                info.remove(child)
        return
    update_authorgroup_authors(info, people, docbook_ns=DOCBOOK_NS)


def _looks_like_imprint_name(name: str) -> bool:
    lowered = name.lower()
    return bool(
        re.search(
            r"\b(books|press|publishers?|publishing|inc\.?|ltd\.?|llc)\b",
            lowered,
        )
    )


def _copyright_holder_from_source(source: SourceIdentityRecord) -> str | None:
    for name in source.authors or []:
        cleaned = str(name).strip()
        if cleaned and _looks_like_imprint_name(cleaned):
            return cleaned
    people = [str(a).strip() for a in (source.authors or []) if str(a).strip()]
    if len(people) == 1:
        return people[0]
    if len(people) > 1:
        return ", ".join(people[:4])
    publisher = (source.publisher or "").strip()
    return publisher or None


def _replace_publisher_biblioset(info: etree._Element, publisher: str | None) -> None:
    """Drop template imprint URLs/addresses; keep a minimal publisher block from the PDF."""
    for biblioset in list(info.findall(f"{{{DOCBOOK_NS}}}biblioset")):
        if biblioset.get("role") in {None, "publisher"}:
            info.remove(biblioset)
    if not publisher:
        return
    biblioset = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioset", attrib={"role": "publisher"})
    pub = etree.SubElement(biblioset, f"{{{DOCBOOK_NS}}}publisher")
    name_el = etree.SubElement(pub, f"{{{DOCBOOK_NS}}}publishername")
    _set_text(name_el, publisher.strip())


def _update_copyright(info: etree._Element, source: SourceIdentityRecord) -> None:
    year = source.publication_year
    holder = _copyright_holder_from_source(source)
    if year is None and not holder:
        return
    copyright_el = _direct_child(info, "copyright")
    if copyright_el is None:
        copyright_el = etree.SubElement(info, f"{{{DOCBOOK_NS}}}copyright")
    else:
        for child in list(iter_element_children(copyright_el)):
            copyright_el.remove(child)
    if year is not None:
        year_el = etree.SubElement(copyright_el, f"{{{DOCBOOK_NS}}}year")
        _set_text(year_el, str(year))
    if holder:
        holder_el = etree.SubElement(copyright_el, f"{{{DOCBOOK_NS}}}holder")
        _set_text(holder_el, holder)


def _update_pubdate(info: etree._Element, year: int | None) -> None:
    if year is None:
        return
    for pubdate in info.findall(f"{{{DOCBOOK_NS}}}pubdate"):
        _set_text(pubdate, str(year))


def _strip_template_marketing_from_info(info: etree._Element) -> None:
    """Remove sample-book covers, blurbs, and CIP blocks when PDF metadata replaces <info>."""
    for local_name in (
        "cover",
        "legalnotice",
        "abstract",
        "keywordset",
        "printhistory",
        "revhistory",
    ):
        for child in list(info.findall(f"{{{DOCBOOK_NS}}}{local_name}")):
            info.remove(child)
    for biblioid in list(info.findall(f"{{{DOCBOOK_NS}}}biblioid")):
        kind = (biblioid.get("class") or "").lower()
        if kind == "other":
            info.remove(biblioid)
def _sync_book_root_id(book: etree._Element, isbn: str | None) -> None:
    if not isbn:
        return
    digits = re.sub(r"[^0-9]", "", isbn.strip())
    if len(digits) >= 10:
        book.set("{http://www.w3.org/XML/1998/namespace}id", f"b-{digits}")


def _append_isbn(info: etree._Element, isbn: str | None) -> None:
    if not isbn:
        return
    biblioid = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioid", attrib={"class": "isbn"})
    set_lxml_text(biblioid, isbn.strip(), log_context={"semantic_type": "metadata", "source": "-", "field": "isbn"})


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

    title = sanitize_xml_text(source.title) if source.title else None
    authors = [sanitize_xml_text(name) for name in (source.authors or []) if sanitize_xml_text(name)]
    publisher = sanitize_xml_text(source.publisher) if source.publisher else None
    isbn = sanitize_xml_text(source.isbn) if source.isbn else None

    has_any = bool(title or isbn or source.publication_year or authors)
    if not has_any:
        result.warnings.append(
            "PDF metadata (title/ISBN/year/authors) was not extracted reliably; "
            "book-level fields were not replaced."
        )
        return result

    _remove_publication_identifiers(info)
    if title:
        _set_or_create_title(info, title.strip())
        _clear_subtitle(info)
    if authors:
        _replace_authorgroup(info, authors)
    _replace_publisher_biblioset(info, publisher)
    _update_copyright(info, source)
    _update_pubdate(info, source.publication_year)
    _append_isbn(info, isbn)
    _strip_template_marketing_from_info(info)
    _sync_book_root_id(book, isbn)

    result.applied = True
    logger.info(
        "docbook_metadata_overlay extraction_id=%s title=%s isbn=%s year=%s",
        source.extraction_id,
        (source.title or "-")[:80],
        source.isbn or "-",
        source.publication_year,
    )
    return result
