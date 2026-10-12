from app.services.layout.book_table_of_contents import (
    is_book_toc_blob,
    parse_table_of_contents_text,
)
from app.services.docbook_toc_front_matter import insert_book_toc_front_matter
from app.services.template_format import DOCBOOK_NS
from lxml import etree


MOSS_GLUED_TOC = (
    "1\t Intellectuals and the Second Spanish Republic12\t "
    "Rafael Alberti: Between Aesthetics and Politics333\t "
    "Pablo Neruda: Epic Revolutionary Poet694\t "
    "Nicol\u00e1s Guill\u00e9n: Racial Democracy105"
)


def test_parse_glued_moss_toc_blob() -> None:
    entries = parse_table_of_contents_text(MOSS_GLUED_TOC)
    assert len(entries) == 4
    assert entries[0].label == "1"
    assert entries[0].title == "Intellectuals and the Second Spanish Republic"
    assert entries[0].page == "1"
    assert entries[1].label == "2"
    assert entries[1].page == "33"
    assert entries[3].label == "4"
    assert entries[3].page == "105"
    assert "Guill" in entries[3].title


def test_parse_formatted_toc_with_prologue() -> None:
    text = """Contents
Prologue vii
1 Intellectuals and the Second Spanish Republic 1
2 Rafael Alberti: Between Aesthetics and Politics 33
Conclusions 137
Bibliography 141
"""
    entries = parse_table_of_contents_text(text)
    titles = [e.title for e in entries]
    assert "Prologue" in titles
    assert "Conclusions" in titles
    assert "Bibliography" in titles


def test_is_book_toc_blob() -> None:
    assert is_book_toc_blob(MOSS_GLUED_TOC)
    assert not is_book_toc_blob("A single normal paragraph about Spain.")


def test_insert_book_toc_strips_control_characters() -> None:
    ns = DOCBOOK_NS
    book = etree.Element(f"{{{ns}}}book")
    entries = [
        {
            "label": "1",
            "title": "Intellectuals\x01 and the Second Spanish Republic",
            "page": "1",
        },
    ]
    insert_book_toc_front_matter(book, entries)
    xml = etree.tostring(book, encoding="unicode")
    assert "\x01" not in xml
    assert "Intellectuals" in xml


def test_insert_book_toc_front_matter() -> None:
    ns = DOCBOOK_NS
    book = etree.Element(f"{{{ns}}}book")
    entries = [
        {"label": "1", "title": "Intellectuals and the Second Spanish Republic", "page": "1"},
        {"label": None, "title": "Prologue", "page": "vii"},
    ]
    assert insert_book_toc_front_matter(book, entries)
    toc = book.find(f".//{{{ns}}}toc")
    assert toc is not None
    tocentries = toc.findall(f".//{{{ns}}}tocentry")
    assert len(tocentries) == 2
    assert tocentries[0].get("pagenum") == "1"
