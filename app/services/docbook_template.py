"""Parse DocBook 5.0 book templates (structure + book-level metadata)."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.models.docbook_template import (
    DocBookBookMetadata,
    DocBookIdentifier,
    DocBookStructureNode,
    DocBookTemplateParseResult,
)
from app.services.template_format import DOCBOOK_NS, classify_template_root
from app.utils.xml_helpers import iter_element_children, xml_local_name


def _text_content(element: etree._Element) -> str:
    return " ".join((element.text or "").split())


def _direct_child(parent: etree._Element, local_name: str) -> etree._Element | None:
    for child in iter_element_children(parent):
        if xml_local_name(child) == local_name:
            return child
    return None


def _person_name_text(personname: etree._Element) -> str | None:
    first = _direct_child(personname, "firstname")
    surname = _direct_child(personname, "surname")
    parts = []
    if first is not None and _text_content(first):
        parts.append(_text_content(first))
    if surname is not None and _text_content(surname):
        parts.append(_text_content(surname))
    joined = " ".join(parts).strip()
    return joined or None


def _authors_from_info(info: etree._Element) -> list[str]:
    authors: list[str] = []
    for authorgroup in info.findall(f"{{{DOCBOOK_NS}}}authorgroup"):
        for author in authorgroup.findall(f"{{{DOCBOOK_NS}}}author"):
            personname = _direct_child(author, "personname")
            if personname is None:
                org = _direct_child(author, "orgname")
                if org is not None:
                    text = _text_content(org)
                    if text:
                        authors.append(text)
                continue
            name = _person_name_text(personname)
            if name:
                authors.append(name)
    return authors


def _publisher_from_info(info: etree._Element) -> str | None:
    for biblioset in info.iter(f"{{{DOCBOOK_NS}}}biblioset"):
        if biblioset.get("role") not in {None, "publisher"}:
            continue
        for publisher in biblioset.iter(f"{{{DOCBOOK_NS}}}publisher"):
            name_el = _direct_child(publisher, "publishername")
            if name_el is not None:
                text = _text_content(name_el)
                if text:
                    return text
        misc = biblioset.find(f".//{{{DOCBOOK_NS}}}bibliomisc[@role='imprint']")
        if misc is not None:
            text = _text_content(misc)
            if text:
                return text
    return None


def _identifiers_from_info(info: etree._Element) -> tuple[list[DocBookIdentifier], str | None]:
    isbns: list[DocBookIdentifier] = []
    book_doi: str | None = None
    for biblioid in info.iter(f"{{{DOCBOOK_NS}}}biblioid"):
        if biblioid.getparent() is not None:
            parent_local = xml_local_name(biblioid.getparent())
            if parent_local in {"bibliomixed", "bibliomisc", "para", "footnote"}:
                continue
        kind = biblioid.get("class") or "other"
        value = _text_content(biblioid)
        if not value:
            continue
        if kind == "isbn":
            isbns.append(DocBookIdentifier(kind="isbn", role=biblioid.get("role"), value=value))
        elif kind == "doi" and book_doi is None:
            if ".ch-" not in value and value.count("/") <= 1:
                book_doi = value
    return isbns, book_doi


def _copyright_from_info(info: etree._Element) -> tuple[str | None, str | None]:
    copyright_el = _direct_child(info, "copyright")
    if copyright_el is None:
        return None, None
    year_el = _direct_child(copyright_el, "year")
    holder_el = _direct_child(copyright_el, "holder")
    year = _text_content(year_el) if year_el is not None else None
    holder = _text_content(holder_el) if holder_el is not None else None
    return year or None, holder or None


def extract_docbook_book_metadata(book: etree._Element) -> DocBookBookMetadata:
    """Read book-level metadata from the direct child ``<info>`` element only."""
    info = _direct_child(book, "info")
    if info is None:
        return DocBookBookMetadata()

    title_el = _direct_child(info, "title")
    subtitle_el = _direct_child(info, "subtitle")
    isbns, doi = _identifiers_from_info(info)
    year, holder = _copyright_from_info(info)

    return DocBookBookMetadata(
        title=_text_content(title_el) if title_el is not None else None,
        subtitle=_text_content(subtitle_el) if subtitle_el is not None else None,
        authors=_authors_from_info(info),
        publisher=_publisher_from_info(info),
        isbns=isbns,
        doi=doi,
        copyright_year=year,
        copyright_holder=holder,
    )


def _structure_node(element: etree._Element, *, max_depth: int, depth: int) -> DocBookStructureNode:
    local = xml_local_name(element)
    ns = element.nsmap.get(None) if element.nsmap else None
    if isinstance(element.tag, str) and element.tag.startswith("{"):
        ns = element.tag.split("}", 1)[0][1:]

    attrs = {k: v for k, v in element.attrib.items()}
    text_preview = None
    if not list(iter_element_children(element)):
        stripped = _text_content(element)
        if stripped:
            text_preview = stripped[:200]

    children: list[DocBookStructureNode] = []
    if depth < max_depth:
        for child in iter_element_children(element):
            children.append(_structure_node(child, max_depth=max_depth, depth=depth + 1))

    return DocBookStructureNode(
        tag=local,
        namespace_uri=ns,
        attributes=attrs,
        text_preview=text_preview,
        children=children,
    )


def parse_docbook_book_tree(
    book: etree._Element,
    *,
    structure_max_depth: int = 12,
) -> DocBookTemplateParseResult:
    root_info = classify_template_root(book)
    metadata = extract_docbook_book_metadata(book)
    structure = _structure_node(book, max_depth=structure_max_depth, depth=0)
    return DocBookTemplateParseResult(
        root_namespace=root_info.namespace_uri or DOCBOOK_NS,
        version=root_info.version,
        metadata=metadata,
        structure=structure,
    )


def parse_docbook_template_file(path: str | Path) -> DocBookTemplateParseResult:
    tree = etree.parse(str(path))
    return parse_docbook_book_tree(tree.getroot())
