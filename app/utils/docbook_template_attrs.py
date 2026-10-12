"""Preserve DocBook template element attributes when updating text from PDF metadata."""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from app.utils.person_name import split_docbook_western_name
from app.utils.xml_helpers import iter_element_children, xml_local_name
from app.utils.xml_text import set_lxml_attr, set_lxml_text

XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def snapshot_element_attributes(element: etree._Element) -> dict[str, str]:
    return dict(element.attrib)


def apply_element_attributes(element: etree._Element, attributes: dict[str, str]) -> None:
    for key, value in attributes.items():
        if value is not None and str(value).strip():
            set_lxml_attr(element, key, value)


def _non_generated_author_attributes(attributes: dict[str, str]) -> dict[str, str]:
    """Drop foreign template biblio IDs; keep DocBook author slot role."""
    filtered: dict[str, str] = {}
    for key, value in attributes.items():
        if not value or not str(value).strip():
            continue
        local = key.split("}", 1)[-1] if key.startswith("{") else key
        if local in {"href"} and (
            key.startswith(f"{{{XLINK_NS}}}") or key.startswith("xlink:")
        ):
            continue
        if key.startswith(f"{{{XLINK_NS}}}") or key.startswith("xlink:"):
            if local == "role" and str(value).strip() == "biblioAuID":
                filtered[key] = str(value).strip()
            continue
        if local == "role" and key.startswith("{") is False:
            continue
        filtered[key] = value
    return filtered


def apply_default_author_xlink_role(author: etree._Element) -> None:
    role_key = f"{{{XLINK_NS}}}role"
    if not (author.get(role_key) or "").strip():
        set_lxml_attr(author, role_key, "biblioAuID")


@dataclass
class _AuthorSlotPrototype:
    author_attributes: dict[str, str] = field(default_factory=dict)
    personname_attributes: dict[str, str] = field(default_factory=dict)


def _author_slots_from_authorgroup(authorgroup: etree._Element) -> list[_AuthorSlotPrototype]:
    slots: list[_AuthorSlotPrototype] = []
    for author in authorgroup:
        if not isinstance(author.tag, str) or xml_local_name(author) != "author":
            continue
        personname = next(
            (child for child in iter_element_children(author) if xml_local_name(child) == "personname"),
            None,
        )
        slots.append(
            _AuthorSlotPrototype(
                author_attributes=snapshot_element_attributes(author),
                personname_attributes=snapshot_element_attributes(personname)
                if personname is not None
                else {},
            )
        )
    return slots


def _set_personname_display_name(personname: etree._Element, display_name: str, docbook_ns: str) -> None:
    first_name, middle, surname = split_docbook_western_name(display_name.strip())
    for child in list(iter_element_children(personname)):
        personname.remove(child)
    personname.text = None
    if "role" in personname.attrib:
        del personname.attrib["role"]
    if first_name or middle or surname:
        set_lxml_attr(personname, "role", "first-last")
    if first_name:
        first = etree.SubElement(personname, f"{{{docbook_ns}}}firstname")
        set_lxml_text(first, first_name)
    if middle:
        other = etree.SubElement(personname, f"{{{docbook_ns}}}othername")
        set_lxml_attr(other, "role", "middle-initials")
        set_lxml_text(other, middle)
    if surname:
        last = etree.SubElement(personname, f"{{{docbook_ns}}}surname")
        set_lxml_text(last, surname)


def _new_author_element(
    authorgroup: etree._Element,
    display_name: str,
    *,
    docbook_ns: str,
    prototype: _AuthorSlotPrototype | None,
) -> etree._Element:
    author = etree.SubElement(authorgroup, f"{{{docbook_ns}}}author")
    if prototype:
        apply_element_attributes(author, _non_generated_author_attributes(prototype.author_attributes))
    apply_default_author_xlink_role(author)

    personname = etree.SubElement(author, f"{{{docbook_ns}}}personname")
    if prototype and prototype.personname_attributes:
        apply_element_attributes(
            personname,
            _non_generated_author_attributes(prototype.personname_attributes),
        )
    _set_personname_display_name(personname, display_name, docbook_ns)
    return author


def update_authorgroup_authors(
    info: etree._Element,
    authors: list[str],
    *,
    docbook_ns: str,
) -> None:
    """Update author names in place, preserving per-slot template attributes when possible."""
    authorgroup = next(
        (child for child in iter_element_children(info) if xml_local_name(child) == "authorgroup"),
        None,
    )
    if authorgroup is None:
        authorgroup = etree.SubElement(info, f"{{{docbook_ns}}}authorgroup")

    prototypes = _author_slots_from_authorgroup(authorgroup)
    default_prototype = prototypes[0] if prototypes else _AuthorSlotPrototype()

    existing_authors = [
        child
        for child in list(iter_element_children(authorgroup))
        if xml_local_name(child) == "author"
    ]
    for author in existing_authors:
        authorgroup.remove(author)

    for index, display_name in enumerate(authors):
        cleaned = display_name.strip()
        if not cleaned:
            continue
        prototype = prototypes[index] if index < len(prototypes) else default_prototype
        _new_author_element(
            authorgroup,
            cleaned,
            docbook_ns=docbook_ns,
            prototype=prototype,
        )
