"""DocBook template attribute preservation during PDF metadata overlay."""

from __future__ import annotations

from lxml import etree

from app.services.docbook_metadata_overlay import apply_pdf_metadata_to_docbook_book
from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS

XLINK_NS = "http://www.w3.org/1999/xlink"
NS = {"db": DOCBOOK_NS, "xlink": XLINK_NS}


def _book_xml() -> etree._Element:
    return etree.fromstring(
        f"""<book xmlns="http://docbook.org/ns/docbook"
          xmlns:xlink="http://www.w3.org/1999/xlink"
          xml:id="b-template">
      <info xml:id="info-template">
        <title sortas="Political and Spiritual" xml:id="title-template">Old Title</title>
        <authorgroup>
          <author xlink:href="367958" xlink:role="biblioAuID">
            <personname role="first-last">
              <firstname>Template</firstname>
              <surname>Author</surname>
            </personname>
          </author>
          <author xlink:href="999999" xlink:role="biblioAuID">
            <personname role="first-last">
              <firstname>Second</firstname>
              <surname>Writer</surname>
            </personname>
          </author>
        </authorgroup>
        <biblioid class="isbn">978-0-000-00000-0</biblioid>
      </info>
    </book>""".encode("utf-8")
    )


def test_title_sortas_preserved_when_pdf_title_applied() -> None:
    root = _book_xml()
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="book.pdf",
        title="Political Poetry in the Wake of the Second",
        authors=["Real Author"],
        publication_year=2018,
        isbn="978-1-4985-4770-3",
    )
    apply_pdf_metadata_to_docbook_book(root, source)
    title = root.xpath("db:info/db:title", namespaces=NS)[0]
    assert title.get("sortas") == "Political and Spiritual"
    assert title.get("{http://www.w3.org/XML/1998/namespace}id") == "title-template"
    assert "Political Poetry" in (title.text or "")


def test_author_xlink_and_personname_role_preserved_per_slot() -> None:
    root = _book_xml()
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="book.pdf",
        title="New Title",
        authors=["Jane Doe", "John Smith"],
        publication_year=2018,
        isbn="978-1-4985-4770-3",
    )
    apply_pdf_metadata_to_docbook_book(root, source)
    authors = root.xpath("db:info/db:authorgroup/db:author", namespaces=NS)
    assert len(authors) == 2
    assert authors[0].get(f"{{{XLINK_NS}}}href") == "367958"
    assert authors[0].get(f"{{{XLINK_NS}}}role") == "biblioAuID"
    assert authors[1].get(f"{{{XLINK_NS}}}href") == "999999"
    personnames = root.xpath("db:info/db:authorgroup/db:author/db:personname", namespaces=NS)
    assert all(node.get("role") == "first-last" for node in personnames)
    assert root.xpath("string(db:info/db:authorgroup/db:author[1]/db:personname/db:firstname)", namespaces=NS) == "Jane"
    assert root.xpath("string(db:info/db:authorgroup/db:author[2]/db:personname/db:surname)", namespaces=NS) == "Smith"


def test_extra_pdf_author_does_not_inherit_template_xlink_id() -> None:
    root = _book_xml()
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="book.pdf",
        title="New Title",
        authors=["Jane Doe", "John Smith", "Extra Person"],
        publication_year=2018,
        isbn="978-1-4985-4770-3",
    )
    apply_pdf_metadata_to_docbook_book(root, source)
    authors = root.xpath("db:info/db:authorgroup/db:author", namespaces=NS)
    assert len(authors) == 3
    assert authors[2].get(f"{{{XLINK_NS}}}href") is None
    assert authors[2].xpath("db:personname/@role", namespaces=NS) == ["first-last"]


def test_pdf_metadata_not_replaced_by_template_sample_names() -> None:
    root = _book_xml()
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="book.pdf",
        title="From PDF",
        authors=["Only PDF Author"],
        publication_year=2020,
        isbn="978-1-111-11111-1",
    )
    apply_pdf_metadata_to_docbook_book(root, source)
    assert (
        root.xpath("string(db:info/db:authorgroup/db:author/db:personname/db:firstname)", namespaces=NS)
        == "Only PDF"
    )
    assert (
        root.xpath("string(db:info/db:authorgroup/db:author/db:personname/db:surname)", namespaces=NS)
        == "Author"
    )
    assert "Template" not in etree.tostring(root, encoding="unicode")
