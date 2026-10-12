"""DocBook book structure normalization after PDF merge."""

from __future__ import annotations

from lxml import etree

from app.services.docbook_structure_fixup import normalize_docbook_book_structure
from app.services.template_format import DOCBOOK_NS
from app.utils.book_running_headers import is_book_running_header_text


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def test_running_header_detection_folio_and_glue() -> None:
    assert is_book_running_header_text("152\tIndex")
    assert is_book_running_header_text("142 Bibliography")
    assert is_book_running_header_text("135 Nicolás Guillén")
    assert is_book_running_header_text("Pablo Neruda103")


def test_dedupe_consecutive_paras_and_unnest_chapters() -> None:
    xml = f"""<book xmlns="http://docbook.org/ns/docbook" xml:id="b-9781498547703">
  <chapter><title>Index</title>
    <chapter><title>About the Author</title><para>Bio.</para></chapter>
    <para>1. Karl Marx and Friedrick Engels, same note.</para>
    <para>1. Karl Marx and Friedrick Engels, same note.</para>
    <para>152 Index</para>
  </chapter>
</book>"""
    root = _parse(xml)
    normalize_docbook_book_structure(root)
    chapters = root.findall(f"{{{DOCBOOK_NS}}}part/{{{DOCBOOK_NS}}}chapter")
    assert len(chapters) == 2
    assert chapters[0].find(f"{{{DOCBOOK_NS}}}info/{{{DOCBOOK_NS}}}title").text == "Index"
    paras = chapters[0].findall(f"{{{DOCBOOK_NS}}}para")
    assert len(paras) == 1
    assert chapters[0].get("{http://www.w3.org/XML/1998/namespace}id") == "b-9781498547703-chapter1"
    assert chapters[1].get("{http://www.w3.org/XML/1998/namespace}id") == "b-9781498547703-chapter2"
    assert chapters[0].get("label") is None
    assert chapters[1].get("label") is None


def test_main_matter_chapters_before_back_matter_and_labels() -> None:
    xml = f"""<book xmlns="http://docbook.org/ns/docbook" xml:id="b-9781498547703">
  <chapter><info><title>Index</title></info><para>Index body</para></chapter>
  <chapter><info><title>Intellectuals and the Second Spanish Republic</title></info><para>Main.</para></chapter>
  <chapter><info><title>About the Author</title></info><para>Bio.</para></chapter>
</book>"""
    root = _parse(xml)
    normalize_docbook_book_structure(root)
    parts = root.findall(f"{{{DOCBOOK_NS}}}part")
    assert len(parts) == 1
    assert parts[0].get("role") == "back"
    main = root.findall(f"{{{DOCBOOK_NS}}}chapter")
    assert len(main) == 1
    assert main[0].find(f"{{{DOCBOOK_NS}}}info/{{{DOCBOOK_NS}}}title").text == (
        "Intellectuals and the Second Spanish Republic"
    )
    assert main[0].get("label") == "1"


def test_bibliography_section_and_global_bibliomixed_dedupe() -> None:
    xml = f"""<book xmlns="http://docbook.org/ns/docbook" xml:id="b-9781498547703">
  <chapter role="bibliography"><title>Bibliography</title>
    <bibliolist>
      <bibliomixed>Ellis, Keith.</bibliomixed>
      <bibliomixed>Ellis, Keith.</bibliomixed>
      <bibliomixed>Williams, Robert.</bibliomixed>
    </bibliolist>
  </chapter>
</book>"""
    root = _parse(xml)
    normalize_docbook_book_structure(root)
    section = root.find(f".//{{{DOCBOOK_NS}}}section[@role='bibliography']")
    assert section is not None
    entries = section.findall(f".//{{{DOCBOOK_NS}}}bibliomixed")
    assert len(entries) == 2
