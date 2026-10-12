"""Preserve DocBook template element attributes when updating text from PDF metadata."""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from app.utils.person_name import split_person_name
from app.utils.xml_helpers import iter_element_children, xml_local_name

XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def snapshot_element_attributes(element: etree._Element) -> dict[str, str]:
    return dict(element.attrib)


def apply_element_attributes(element: etree._Element, attributes: dict[str, str]) -> None:
    for key, value in attributes.items():
        if value is not None:
            element.set(key, value)


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
    given, surname = split_person_name(display_name.strip())
    for child in list(iter_element_children(personname)):
        personname.remove(child)
    personname.text = None
    if given:
        first = etree.SubElement(personname, f"{{{docbook_ns}}}firstname")
        first.text = given
    if surname:
        last = etree.SubElement(personname, f"{{{docbook_ns}}}surname")
        last.text = surname


def _new_author_element(
    authorgroup: etree._Element,
    display_name: str,
    *,
    docbook_ns: str,
    prototype: _AuthorSlotPrototype | None,
    inherit_external_ids: bool,
) -> etree._Element:
    author = etree.SubElement(authorgroup, f"{{{docbook_ns}}}author")
    if prototype and inherit_external_ids:
        apply_element_attributes(author, prototype.author_attributes)
    elif prototype:
        filtered = {
            key: value
            for key, value in prototype.author_attributes.items()
            if not key.startswith(f"{{{XLINK_NS}}}")
            and not key.startswith("xlink:")
        }
        apply_element_attributes(author, filtered)

    personname = etree.SubElement(author, f"{{{docbook_ns}}}personname")
    if prototype and prototype.personname_attributes:
        apply_element_attributes(personname, prototype.personname_attributes)
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
        inherit_ids = index < len(prototypes)
        _new_author_element(
            authorgroup,
            cleaned,
            docbook_ns=docbook_ns,
            prototype=prototype,
            inherit_external_ids=inherit_ids,
        )
