"""Insert DocBook front-matter ``<toc>`` from parsed PDF table of contents."""

from __future__ import annotations

from lxml import etree

from app.services.template_format import DOCBOOK_NS
from app.utils.xml_helpers import iter_element_children, xml_local_name
from app.utils.xml_text import sanitize_xml_text, set_lxml_attr, set_lxml_text


def _ns(tag: str) -> str:
    return f"{{{DOCBOOK_NS}}}{tag}"


def insert_book_toc_front_matter(
    book: etree._Element,
    entries: list[dict[str, str | None]],
) -> bool:
    """Add ``<part role=\"front\"><toc>…</toc></part>`` when PDF TOC entries exist."""
    if not entries:
        return False
    part: etree._Element | None = None
    for child in iter_element_children(book):
        if xml_local_name(child) == "part" and (child.get("role") or "").strip() == "front":
            part = child
            break
    if part is None:
        info = next((c for c in iter_element_children(book) if xml_local_name(c) == "info"), None)
        insert_at = list(book).index(info) + 1 if info is not None else 0
        part = etree.Element(_ns("part"))
        part.set("role", "front")
        part_info = etree.SubElement(part, _ns("info"))
        part_title = etree.SubElement(part_info, _ns("title"))
        set_lxml_text(part_title, "Front matter")
        book.insert(insert_at, part)

    for child in list(iter_element_children(part)):
        if xml_local_name(child) == "toc":
            part.remove(child)

    toc = etree.SubElement(part, _ns("toc"))
    toc_info = etree.SubElement(toc, _ns("info"))
    toc_title = etree.SubElement(toc_info, _ns("title"))
    set_lxml_text(toc_title, "Contents")

    tocdiv = etree.SubElement(toc, _ns("tocdiv"))
    div_title = etree.SubElement(tocdiv, _ns("title"))
    set_lxml_text(div_title, "Contents")

    for item in entries:
        title_text = sanitize_xml_text((item.get("title") or "").strip())
        page = sanitize_xml_text((item.get("page") or "").strip())
        label_raw = item.get("label")
        label = sanitize_xml_text(str(label_raw).strip()) if label_raw else ""
        if not title_text:
            continue
        entry = etree.SubElement(tocdiv, _ns("tocentry"))
        if page:
            set_lxml_attr(entry, "pagenum", page)
        title_el = etree.SubElement(entry, _ns("title"))
        if label:
            emph = etree.SubElement(title_el, _ns("emphasis"))
            emph.set("role", "bold")
            set_lxml_text(emph, label)
            set_lxml_text(title_el, f" {title_text}", tail=True)
        else:
            set_lxml_text(title_el, title_text)
    return True
