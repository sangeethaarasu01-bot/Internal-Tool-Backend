"""Assign DocBook ``xml:id`` values from the selected ISBN-13 (metadata / ``<info>`` only)."""

from __future__ import annotations

from lxml import etree

from app.utils.isbn_selection import book_root_xml_id, isbn13_digits
from app.utils.xml_helpers import iter_element_children, xml_local_name

XML_ID_ATTR = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG_ATTR = "{http://www.w3.org/XML/1998/namespace}lang"
_INVALID_XML_LANG_ATTR = "xml_lang"

# Container elements under <info> that may receive generated xml:id (not leaves).
_INFO_ID_CONTAINERS = frozenset(
    {
        "title",
        "subtitle",
        "authorgroup",
        "author",
        "personblurb",
        "publisher",
        "address",
        "abstract",
        "keywordset",
        "biblioset",
        "legalnotice",
        "copyright",
        "revision",
    }
)


def _clear_xml_ids_under(root: etree._Element) -> None:
    for element in root.iter():
        if XML_ID_ATTR in element.attrib:
            del element.attrib[XML_ID_ATTR]


def _assign_info_child_ids(info: etree._Element, root_id: str) -> None:
    sequence = 1
    info.set(XML_ID_ATTR, f"{root_id}-{sequence:07d}")
    sequence += 1

    def walk(parent: etree._Element) -> None:
        nonlocal sequence
        for child in iter_element_children(parent):
            local = xml_local_name(child)
            if local in _INFO_ID_CONTAINERS:
                child.set(XML_ID_ATTR, f"{root_id}-{sequence:07d}")
                sequence += 1
            walk(child)

    walk(info)


def normalize_docbook_book_xml_language(book: etree._Element, lang: str = "en") -> None:
    """
    Ensure ``xml:lang`` appears once on ``<book>`` only (Clark notation in the DOM).

    Removes invalid ``xml_lang`` keys and ``xml:lang`` on descendants.
    """
    language = (lang or "en").strip() or "en"
    for element in book.iter():
        if _INVALID_XML_LANG_ATTR in element.attrib:
            del element.attrib[_INVALID_XML_LANG_ATTR]
        if element is not book and XML_LANG_ATTR in element.attrib:
            del element.attrib[XML_LANG_ATTR]
    book.set(XML_LANG_ATTR, language)


def apply_docbook_book_root_attributes(book: etree._Element) -> None:
    book.set("version", "5.0")
    normalize_docbook_book_xml_language(book)
    if not (book.get("role") or "").strip():
        book.set("role", "fullText")


def assign_docbook_metadata_xml_ids(book: etree._Element, primary_isbn: str | None) -> str | None:
    """
    Set root ``<book>`` id to ``b-{isbn13}`` and sequential ids on ``<info>`` containers only.

    Does not modify xml:ids on chapters or other body structure.
    """
    digits = isbn13_digits(primary_isbn)
    root_id = book_root_xml_id(primary_isbn)
    if not digits or not root_id:
        if XML_ID_ATTR in book.attrib:
            del book.attrib[XML_ID_ATTR]
        return None

    book.set(XML_ID_ATTR, root_id)
    apply_docbook_book_root_attributes(book)

    info = next(
        (child for child in iter_element_children(book) if xml_local_name(child) == "info"),
        None,
    )
    if info is not None:
        _clear_xml_ids_under(info)
        _assign_info_child_ids(info, root_id)
    return root_id


# Backward-compatible alias used by overlay.
def assign_docbook_xml_ids(book: etree._Element, primary_isbn: str | None) -> str | None:
    return assign_docbook_metadata_xml_ids(book, primary_isbn)
