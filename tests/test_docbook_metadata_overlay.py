"""Unit tests for DocBook book-level metadata overlay."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.services.docbook_metadata_overlay import apply_pdf_metadata_to_docbook_book
from app.services.docbook_template import extract_docbook_book_metadata
from app.services.source_identity import SourceIdentityRecord

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
