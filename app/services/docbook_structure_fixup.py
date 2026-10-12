"""Normalize DocBook 5.0 book body structure after PDF merge."""

from __future__ import annotations

import re

from lxml import etree

from app.services.template_format import DOCBOOK_NS
from app.utils.book_running_headers import is_book_running_header_text
from app.utils.xml_helpers import iter_element_children, xml_local_name

XML_ID_ATTR = "{http://www.w3.org/XML/1998/namespace}id"

_BACK_MATTER_TITLES = frozenset(
    {
        "index",
        "about the author",
        "about the authors",
        "colophon",
    }
)
_BIBLIOGRAPHY_TITLES = frozenset({"bibliography", "references", "works cited"})


def _ns(tag: str) -> str:
    return f"{{{DOCBOOK_NS}}}{tag}"


def _normalize_text_key(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _chapter_title(chapter: etree._Element) -> str:
    info = _direct_child(chapter, "info")
    if info is not None:
        title = _direct_child(info, "title")
        if title is not None and (title.text or "").strip():
            return (title.text or "").strip()
    title = _direct_child(chapter, "title")
    if title is not None and (title.text or "").strip():
        return (title.text or "").strip()
    return ""


def _direct_child(parent: etree._Element, local_name: str) -> etree._Element | None:
    for child in iter_element_children(parent):
        if xml_local_name(child) == local_name:
            return child
    return None


def _remove_running_header_elements(root: etree._Element) -> None:
    for para in list(root.iter(_ns("para"))):
        text = _normalize_text_key("".join(para.itertext()))
        if text and is_book_running_header_text(text):
            parent = para.getparent()
            if parent is not None:
                parent.remove(para)


def _remove_book_toc_paragraphs(root: etree._Element) -> None:
    from app.services.layout.book_table_of_contents import is_book_toc_blob

    for para in list(root.iter(_ns("para"))):
        text = _normalize_text_key("".join(para.itertext()))
        if text and is_book_toc_blob(text):
            parent = para.getparent()
            if parent is not None:
                parent.remove(para)


def _dedupe_repeated_siblings(parent: etree._Element) -> None:
    prev_key: str | None = None
    for child in list(iter_element_children(parent)):
        local = xml_local_name(child)
        if local in {"para", "bibliomixed"}:
            key = _normalize_text_key("".join(child.itertext()))
            if key and key == prev_key:
                parent.remove(child)
                continue
            prev_key = key if key else None
        else:
            prev_key = None
            _dedupe_repeated_siblings(child)

    bibliolist = _direct_child(parent, "bibliolist")
    if bibliolist is not None:
        seen: set[str] = set()
        for entry in list(iter_element_children(bibliolist)):
            if xml_local_name(entry) != "bibliomixed":
                continue
            key = _normalize_text_key("".join(entry.itertext()))
            if not key:
                continue
            if key in seen:
                bibliolist.remove(entry)
            else:
                seen.add(key)


def _unwrap_nested_chapters(book: etree._Element) -> None:
    """Promote nested <chapter> elements to siblings (DocBook disallows chapter in chapter)."""
    changed = True
    while changed:
        changed = False
        for chapter in list(book.iter(_ns("chapter"))):
            nested = [
                c for c in iter_element_children(chapter) if xml_local_name(c) == "chapter"
            ]
            if not nested:
                continue
            parent = chapter.getparent()
            if parent is None:
                continue
            insert_at = parent.index(chapter) + 1
            for child_ch in nested:
                chapter.remove(child_ch)
                parent.insert(insert_at, child_ch)
                insert_at += 1
                changed = True


def _ensure_chapter_info_title(chapter: etree._Element) -> None:
    info = _direct_child(chapter, "info")
    bare_title = _direct_child(chapter, "title")
    if info is None:
        info = etree.Element(_ns("info"))
        chapter.insert(0, info)
    title = _direct_child(info, "title")
    if title is None and bare_title is not None:
        chapter.remove(bare_title)
        info.append(bare_title)
    elif title is None:
        etree.SubElement(info, _ns("title"))


def _convert_bibliography_chapters(book: etree._Element) -> None:
    for chapter in list(iter_element_children(book)):
        if xml_local_name(chapter) != "chapter":
            continue
        role = (chapter.get("role") or "").strip().lower()
        title_text = _chapter_title(chapter).strip().lower()
        is_bib = role == "bibliography" or title_text in _BIBLIOGRAPHY_TITLES
        if not is_bib:
            continue
        _ensure_chapter_info_title(chapter)
        if _direct_child(chapter, "section") is not None:
            continue
        bibliolist = _direct_child(chapter, "bibliolist")
        if bibliolist is None:
            bibliolist = next(
                (el for el in chapter.iter(_ns("bibliolist"))),
                None,
            )
        section = etree.SubElement(chapter, _ns("section"))
        section.set("role", "bibliography")
        sec_info = etree.SubElement(section, _ns("info"))
        sec_title = etree.SubElement(sec_info, _ns("title"))
        sec_title.text = _chapter_title(chapter) or "Bibliography"
        if bibliolist is not None and bibliolist.getparent() is chapter:
            chapter.remove(bibliolist)
            section.append(bibliolist)
        for child in list(iter_element_children(chapter)):
            local = xml_local_name(child)
            if local in {"info", "section"}:
                continue
            if local == "bibliolist":
                continue
            chapter.remove(child)


def _reorder_main_matter_before_back(book: etree._Element) -> None:
    """Move stray back-matter chapters that appear before main narrative."""
    mains: list[etree._Element] = []
    backs: list[etree._Element] = []
    other: list[etree._Element] = []
    for child in iter_element_children(book):
        local = xml_local_name(child)
        if local == "info":
            continue
        if local == "chapter":
            if _chapter_title(child).strip().lower() in _BACK_MATTER_TITLES:
                backs.append(child)
            else:
                mains.append(child)
        else:
            other.append(child)
    if not backs or not mains:
        return
    for child in mains + backs:
        if child.getparent() is book:
            book.remove(child)
    for child in other:
        if child.getparent() is book:
            book.remove(child)
    insert_at = 1 if _direct_child(book, "info") is not None else 0
    for offset, child in enumerate(mains + other + backs):
        book.insert(insert_at + offset, child)


def _group_back_matter(book: etree._Element) -> None:
    back_chapters: list[etree._Element] = []
    for child in iter_element_children(book):
        if xml_local_name(child) != "chapter":
            continue
        if _chapter_title(child).strip().lower() in _BACK_MATTER_TITLES:
            back_chapters.append(child)
    if not back_chapters:
        return
    first_parent = back_chapters[0].getparent()
    if (
        first_parent is not None
        and xml_local_name(first_parent) == "part"
        and (first_parent.get("role") or "").strip() == "back"
    ):
        return
    part = etree.Element(_ns("part"))
    part.set("role", "back")
    part_info = etree.SubElement(part, _ns("info"))
    part_title = etree.SubElement(part_info, _ns("title"))
    part_title.text = "Back matter"
    book.insert(book.index(back_chapters[0]), part)
    for chapter in back_chapters:
        if chapter.getparent() is book:
            book.remove(chapter)
            part.append(chapter)


def _split_index_paragraphs(chapter: etree._Element) -> None:
    if _chapter_title(chapter).strip().lower() != "index":
        return
    for para in list(chapter.iter(_ns("para"))):
        text = para.text or ""
        if len(text) < 2000 or para.getparent() is not chapter:
            continue
        chunks = re.split(r"(?<=\n)(?=[A-Z]\n)", text)
        if len(chunks) <= 1:
            chunks = re.split(r"\n(?=[A-Z]\s)", text)
        if len(chunks) <= 1:
            return
        parent = para.getparent()
        if parent is None:
            return
        pos = parent.index(para)
        parent.remove(para)
        for offset, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            new_para = etree.Element(_ns("para"))
            new_para.text = chunk
            parent.insert(pos + offset, new_para)


def _assign_chapter_ids_and_labels(book: etree._Element, root_id: str) -> None:
    chapter_index = 0
    main_label = 0
    for element in book.iter():
        if xml_local_name(element) != "chapter":
            continue
        chapter_index += 1
        _ensure_chapter_info_title(element)
        element.set(XML_ID_ATTR, f"{root_id}-chapter{chapter_index}")
        parent = element.getparent()
        in_back_part = (
            parent is not None
            and xml_local_name(parent) == "part"
            and (parent.get("role") or "").strip() == "back"
        )
        title_text = _chapter_title(element).strip().lower()
        if not in_back_part and title_text not in _BACK_MATTER_TITLES:
            main_label += 1
            element.set("label", str(main_label))
        elif "label" in element.attrib:
            del element.attrib["label"]


def normalize_docbook_book_structure(book: etree._Element) -> None:
    """
    Repair common PDF-merge DocBook issues: duplicate blocks, nested chapters,
    back-matter grouping, bibliography sections, chapter info/title, and xml:ids.
    """
    root_id = (book.get(XML_ID_ATTR) or "").strip() or "b-book"
    _remove_running_header_elements(book)
    _remove_book_toc_paragraphs(book)
    _dedupe_repeated_recurse(book)
    _unwrap_nested_chapters(book)
    _convert_bibliography_chapters(book)
    _reorder_main_matter_before_back(book)
    _group_back_matter(book)
    for chapter in book.iter(_ns("chapter")):
        if _chapter_title(chapter).strip().lower() == "index":
            _ensure_chapter_info_title(chapter)
            _split_index_paragraphs(chapter)
    _assign_chapter_ids_and_labels(book, root_id)


def _dedupe_repeated_recurse(root: etree._Element) -> None:
    _dedupe_repeated_siblings(root)
    for child in iter_element_children(root):
        _dedupe_repeated_recurse(child)
