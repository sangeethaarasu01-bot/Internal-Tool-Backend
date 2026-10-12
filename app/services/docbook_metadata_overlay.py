"""Replace book-level publication metadata in a DocBook template with PDF extraction identity."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from lxml import etree

from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS

XLINK_NS = "http://www.w3.org/1999/xlink"
etree.register_namespace("xlink", XLINK_NS)
from app.utils.docbook_sortas import apply_sortas_to_title_element
from app.utils.docbook_template_attrs import update_authorgroup_authors
from app.utils.docbook_xml_ids import assign_docbook_metadata_xml_ids
from app.utils.isbn_selection import (
    isbn13_digits,
    normalize_isbn_biblioid_role,
    select_primary_isbn_from_lists,
)
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


def _set_or_clear_subtitle(info: etree._Element, subtitle: str | None) -> None:
    subtitle_el = _direct_child(info, "subtitle")
    cleaned = (subtitle or "").strip()
    if not cleaned:
        if subtitle_el is not None:
            info.remove(subtitle_el)
        return
    if subtitle_el is None:
        title_el = _direct_child(info, "title")
        insert_at = list(info).index(title_el) + 1 if title_el is not None else 0
        subtitle_el = etree.Element(f"{{{DOCBOOK_NS}}}subtitle")
        info.insert(insert_at, subtitle_el)
    _set_text(subtitle_el, cleaned)


def _replace_authorgroup(
    info: etree._Element,
    authors: list[str],
    *,
    author_blurb: str | None = None,
) -> None:
    people = [name.strip() for name in authors if name.strip()]
    people = [name for name in people if not _looks_like_imprint_name(name)]
    if not people:
        for child in list(iter_element_children(info)):
            if xml_local_name(child) == "authorgroup":
                info.remove(child)
        return
    update_authorgroup_authors(info, people, docbook_ns=DOCBOOK_NS)
    blurb = (author_blurb or "").strip()
    if not blurb:
        return
    authorgroup = _direct_child(info, "authorgroup")
    if authorgroup is None:
        return
    author_el = next(
        (child for child in iter_element_children(authorgroup) if xml_local_name(child) == "author"),
        None,
    )
    if author_el is None:
        return
    for child in list(iter_element_children(author_el)):
        if xml_local_name(child) == "personblurb":
            author_el.remove(child)
    blurb_el = etree.SubElement(author_el, f"{{{DOCBOOK_NS}}}personblurb")
    para = etree.SubElement(blurb_el, f"{{{DOCBOOK_NS}}}para")
    _set_text(para, blurb)


def _looks_like_imprint_name(name: str) -> bool:
    lowered = name.lower()
    return bool(
        re.search(
            r"\b(books|press|publishers?|publishing|inc\.?|ltd\.?|llc)\b",
            lowered,
        )
    )


def _copyright_holder_from_source(source: SourceIdentityRecord) -> str | None:
    explicit = (source.copyright_holder or "").strip()
    if explicit:
        return explicit
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


def _append_publisher_address(
    publisher_el: etree._Element,
    address: dict[str, str | None],
) -> None:
    street = (address.get("street") or "").strip()
    city = (address.get("city") or "").strip()
    state = (address.get("state") or "").strip()
    post_code = (address.get("post_code") or "").strip()
    country = (address.get("country") or "").strip()
    website = (address.get("website") or "").strip()
    if not any((street, city, state, post_code, country, website)):
        return
    address_el = etree.SubElement(publisher_el, f"{{{DOCBOOK_NS}}}address")
    if street:
        street_el = etree.SubElement(address_el, f"{{{DOCBOOK_NS}}}street")
        _set_text(street_el, street)
    if city:
        city_el = etree.SubElement(address_el, f"{{{DOCBOOK_NS}}}city")
        _set_text(city_el, city)
    if state:
        state_el = etree.SubElement(address_el, f"{{{DOCBOOK_NS}}}state")
        _set_text(state_el, state)
    if post_code:
        post_el = etree.SubElement(address_el, f"{{{DOCBOOK_NS}}}post-code")
        _set_text(post_el, post_code)
    if country:
        country_el = etree.SubElement(address_el, f"{{{DOCBOOK_NS}}}country")
        _set_text(country_el, country)
    if website:
        link_el = etree.SubElement(address_el, f"{{{DOCBOOK_NS}}}link")
        link_el.set(f"{{{XLINK_NS}}}href", website)
        uri_el = etree.SubElement(link_el, f"{{{DOCBOOK_NS}}}uri")
        _set_text(uri_el, website.replace("https://", "").replace("http://", ""))


def _replace_publisher_biblioset(
    info: etree._Element,
    publisher: str | None,
    *,
    imprint: str | None = None,
    addresses: list[dict[str, str | None]] | None = None,
) -> None:
    """Imprint brand in bibliomisc; parent company in publishername."""
    for biblioset in list(info.findall(f"{{{DOCBOOK_NS}}}biblioset")):
        if biblioset.get("role") in {None, "publisher"}:
            info.remove(biblioset)
    if not publisher and not imprint:
        return
    biblioset = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioset", attrib={"role": "publisher"})
    imprint_name = (imprint or "").strip()
    if imprint_name:
        misc = etree.SubElement(biblioset, f"{{{DOCBOOK_NS}}}bibliomisc", attrib={"role": "imprint"})
        _set_text(misc, imprint_name)
    if not publisher:
        return
    pub = etree.SubElement(biblioset, f"{{{DOCBOOK_NS}}}publisher")
    name_el = etree.SubElement(pub, f"{{{DOCBOOK_NS}}}publishername")
    _set_text(name_el, publisher.strip())
    for address in addresses or []:
        _append_publisher_address(pub, address)


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
    pubdate = _direct_child(info, "pubdate")
    if pubdate is None:
        pubdate = etree.SubElement(info, f"{{{DOCBOOK_NS}}}pubdate", attrib={"role": "published"})
    elif not (pubdate.get("role") or "").strip():
        pubdate.set("role", "published")
    _set_text(pubdate, str(year))


def _insert_missing_comment(info: etree._Element, message: str) -> None:
    info.append(etree.Comment(f" {message} "))


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
def _sync_isbns(
    info: etree._Element,
    isbns: list[str],
    primary_isbn: str | None,
    isbn_roles: dict[str, str],
) -> None:
    values = [v.strip() for v in isbns if v and v.strip()]
    if not values and primary_isbn:
        values = [primary_isbn.strip()]
    if not values:
        return
    if len(values) == 1:
        biblioid = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioid", attrib={"class": "isbn"})
        set_lxml_text(
            biblioid,
            values[0],
            log_context={"semantic_type": "metadata", "source": "-", "field": "isbn"},
        )
        return
    biblioset = etree.SubElement(info, f"{{{DOCBOOK_NS}}}biblioset", attrib={"role": "isbns"})
    for value in values[:4]:
        attrs: dict[str, str] = {"class": "isbn"}
        role = normalize_isbn_biblioid_role(isbn_roles.get(value))
        if role:
            attrs["role"] = role
        biblioid = etree.SubElement(biblioset, f"{{{DOCBOOK_NS}}}biblioid", attrib=attrs)
        set_lxml_text(
            biblioid,
            value,
            log_context={"semantic_type": "metadata", "source": "-", "field": "isbn"},
        )


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
    subtitle = sanitize_xml_text(source.subtitle) if source.subtitle else None
    authors = [sanitize_xml_text(name) for name in (source.authors or []) if sanitize_xml_text(name)]
    publisher = sanitize_xml_text(source.publisher) if source.publisher else None
    publisher_imprint = (
        sanitize_xml_text(source.publisher_imprint) if source.publisher_imprint else None
    )
    isbns = [sanitize_xml_text(v) for v in (source.isbns or []) if sanitize_xml_text(v)]
    role_map = {sanitize_xml_text(v): r for v, r in (source.isbn_roles or []) if v and r}
    isbn = select_primary_isbn_from_lists(
        isbns,
        fallback=sanitize_xml_text(source.isbn) if source.isbn else None,
        qualifiers=role_map,
    )

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
    else:
        _insert_missing_comment(info, "MISSING: title")
    if title or subtitle:
        _set_or_clear_subtitle(info, subtitle)
    author_people = [name for name in authors if not _looks_like_imprint_name(name)]
    author_blurb = sanitize_xml_text(source.author_blurb) if source.author_blurb else None
    if author_people:
        _replace_authorgroup(info, author_people, author_blurb=author_blurb)
    else:
        _insert_missing_comment(info, "MISSING AUTHOR: please supply")
    _replace_publisher_biblioset(
        info,
        publisher,
        imprint=publisher_imprint,
        addresses=list(source.publisher_addresses or []),
    )
    _update_copyright(info, source)
    _update_pubdate(info, source.publication_year)
    _sync_isbns(info, isbns, isbn, role_map)
    _strip_template_marketing_from_info(info)
    if isbn13_digits(isbn):
        assign_docbook_metadata_xml_ids(book, isbn)
    elif book.get("{http://www.w3.org/XML/1998/namespace}id"):
        book.attrib.pop("{http://www.w3.org/XML/1998/namespace}id", None)
        result.warnings.append(
            "No ISBN-13 was available from the PDF; book xml:id was omitted."
        )
    elif not isbn:
        result.warnings.append(
            "No ISBN was available from the PDF; book xml:id was omitted."
        )
    else:
        result.warnings.append(
            "ISBN from the PDF is not a valid ISBN-13; book xml:id was omitted."
        )

    result.applied = True
    logger.info(
        "docbook_metadata_overlay extraction_id=%s title=%s isbn=%s year=%s",
        source.extraction_id,
        (source.title or "-")[:80],
        source.isbn or "-",
        source.publication_year,
    )
    return result
