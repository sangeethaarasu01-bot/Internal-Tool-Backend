"""Unit tests for DocBook book-level metadata overlay."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.services.docbook_metadata_overlay import apply_pdf_metadata_to_docbook_book
from app.services.docbook_template import extract_docbook_book_metadata
from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "minimal_docbook_book.xml"


def test_overlay_replaces_title_isbn_and_keeps_chapter_structure() -> None:
    root = etree.parse(str(FIXTURE)).getroot()
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="a.pdf",
        title="From PDF Title",
        authors=["Jane Editor", "John Writer"],
        publisher="PDF Publisher",
        publication_year=2010,
        isbn="978-0-7391-2360-7",
    )
    result = apply_pdf_metadata_to_docbook_book(root, source)
    assert result.applied
    meta = extract_docbook_book_metadata(root)
    assert meta.title == "From PDF Title"
    assert meta.subtitle is None
    assert any("978-0-7391-2360-7" in i.value for i in meta.isbns)
    assert meta.copyright_year == "2010"
    assert "Chapter One" in etree.tostring(root, encoding="unicode")
    copyright_el = root.find(f".//{{{DOCBOOK_NS}}}copyright")
    assert copyright_el is not None
    holder = copyright_el.find(f".//{{{DOCBOOK_NS}}}holder")
    assert holder is not None and (holder.text or "").strip() == "Jane Editor, John Writer"


def test_overlay_strips_template_publisher_links_revhistory_and_workflow_biblioids() -> None:
    from app.services.template_format import DOCBOOK_NS

    ns = {"db": DOCBOOK_NS}
    root = etree.fromstring(
        f"""<book xmlns="http://docbook.org/ns/docbook"
          xmlns:xlink="http://www.w3.org/1999/xlink">
      <info>
        <title>Old</title>
        <biblioset role="publisher">
          <publisher>
            <publishername>Old Pub</publishername>
            <address><link xlink:href="http://www.rowman.com"><uri>www.rowman.com</uri></link></address>
          </publisher>
        </biblioset>
        <copyright><year>2014</year><holder>Jeff C. Marshall</holder></copyright>
        <biblioid class="other" otherclass="schemaVersion">1</biblioid>
        <revhistory><revision><date>2014-05-09</date></revision></revhistory>
      </info>
    </book>""".encode("utf-8")
    )
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="pastoral.pdf",
        title="Pastoral Bearings",
        authors=["Lexington Books"],
        publisher="Rowman & Littlefield",
        publication_year=2010,
        isbn="978-0-7391-2360-7",
    )
    apply_pdf_metadata_to_docbook_book(root, source)
    xml = etree.tostring(root, encoding="unicode")
    assert "rowman.com" not in xml
    assert "Jeff C. Marshall" not in xml
    assert "revhistory" not in xml
    assert "schemaVersion" not in xml
    holder = root.xpath("string(.//db:copyright/db:holder)", namespaces=ns)
    assert holder.strip() == "Lexington Books"
    pub = root.xpath("string(.//db:publishername)", namespaces=ns)
    assert "Rowman" in pub
