from __future__ import annotations

from lxml import etree

from app.services.template_format import DOCBOOK_NS
from app.utils.docbook_xml_ids import (
    XML_LANG_ATTR,
    apply_docbook_book_root_attributes,
    normalize_docbook_book_xml_language,
)
from app.utils.xml_serializer import serialize_lxml_tree


def test_book_root_xml_lang_clark_not_xml_lang_underscore() -> None:
    book = etree.Element(f"{{{DOCBOOK_NS}}}book", nsmap={None: DOCBOOK_NS})
    book.set("xml_lang", "en")
    child = etree.SubElement(book, f"{{{DOCBOOK_NS}}}info")
    child.set(XML_LANG_ATTR, "en")

    normalize_docbook_book_xml_language(book)

    assert book.get(XML_LANG_ATTR) == "en"
    assert "xml_lang" not in book.attrib
    assert XML_LANG_ATTR not in child.attrib

    xml = serialize_lxml_tree(book, xml_declaration=False, pretty_print=False, text_escape_mode="docbook")
    assert 'xml:lang="en"' in xml
    assert "xml_lang" not in xml
    assert xml.count('xml:lang="en"') == 1


def test_apply_docbook_book_root_attributes_sets_xml_lang() -> None:
    book = etree.Element(f"{{{DOCBOOK_NS}}}book", nsmap={None: DOCBOOK_NS})
    apply_docbook_book_root_attributes(book)
    assert book.get(XML_LANG_ATTR) == "en"
    assert book.get("version") == "5.0"
