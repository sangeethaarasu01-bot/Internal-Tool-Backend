from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.services.ocr_detector import document_requires_ocr, page_requires_ocr
from app.services.text_extractor import PdfValidationError, extract_text_layout


def _write_text_pdf(path: Path, pages: list[str], metadata: dict | None = None) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 100), text, fontsize=12, fontname="helv")
    if metadata:
        doc.set_metadata(metadata)
    doc.save(path)
    doc.close()


def test_normal_digital_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    _write_text_pdf(pdf, ["IEEE Sensors Journal sample abstract paragraph."])

    result = extract_text_layout(str(pdf), original_filename="paper.pdf")

    assert result.document.page_count == 1
    assert result.document.filename == "paper.pdf"
    assert result.document.extraction_engine == "pymupdf"
    assert result.document.ocr_applied is False
    assert result.stats.total_chars > 0
    assert result.stats.total_blocks >= 1
    assert result.stats.total_lines >= 1
    page = result.pages[0]
    assert page.page_number == 1
    assert page.width > 0 and page.height > 0
    assert len(page.blocks) >= 1
    block = page.blocks[0]
    assert len(block.bbox) == 4
    assert block.lines
    line = block.lines[0]
    assert line.spans
    span = line.spans[0]
    assert "IEEE" in span.text or "sample" in page.blocks[0].text
    assert len(span.bbox) == 4
    assert span.font
    assert span.size and span.size > 0


def test_multi_page_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "multi.pdf"
    _write_text_pdf(pdf, ["Page one content.", "Page two content.", "Page three content."])

    result = extract_text_layout(str(pdf))

    assert result.document.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert all(page.text_char_count > 0 for page in result.pages)
    assert all(page.blocks for page in result.pages)


def test_pdf_with_little_text_requires_ocr_not_applied(tmp_path: Path) -> None:
    pdf = tmp_path / "scanned-like.pdf"
    _write_text_pdf(pdf, ["", "", ""])

    result = extract_text_layout(str(pdf))

    assert result.document.requires_ocr is True
    assert result.document.ocr_applied is False
    assert result.stats.pages_with_no_text == [1, 2, 3]
    assert all(page.requires_ocr for page in result.pages)


def test_metadata_captured(tmp_path: Path) -> None:
    pdf = tmp_path / "meta.pdf"
    _write_text_pdf(
        pdf,
        ["Title page body text for extraction."],
        metadata={
            "title": "A Customized Electronic Tongue",
            "author": "Test Author",
            "creator": "pytest",
            "producer": "pymupdf",
        },
    )

    result = extract_text_layout(str(pdf))
    meta = result.document.metadata
    assert meta.title == "A Customized Electronic Tongue"
    assert meta.author == "Test Author"
    assert meta.creator == "pytest"
    assert meta.producer == "pymupdf"


def test_invalid_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"this is not a pdf file")

    with pytest.raises(PdfValidationError):
        extract_text_layout(str(pdf))


def test_empty_page_does_not_crash(tmp_path: Path) -> None:
    pdf = tmp_path / "empty-page.pdf"
    _write_text_pdf(pdf, [""])

    result = extract_text_layout(str(pdf))
    assert result.document.page_count == 1
    assert result.pages[0].text_char_count == 0
    assert result.pages[0].requires_ocr is True
    assert page_requires_ocr(0) is True
    assert document_requires_ocr([0]) is True


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PdfValidationError):
        extract_text_layout(str(tmp_path / "missing.pdf"))
