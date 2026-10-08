from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.pipeline.phase1.extract import Phase1ExtractionError, extract_pdf_document
from app.pipeline.phase1.pdf_kind import classify_pdf_document_kind
from app.services.text_extractor import extract_text_layout


def _write_text_pdf(path: Path, pages: list[str]) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 100), text, fontsize=12, fontname="helv")
            page.insert_text((72, 130), "I. INTRODUCTION", fontsize=14, fontname="helv")
            page.insert_text((72, 160), "Body paragraph for section one.", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_phase1_extract_produces_document_ir(tmp_path: Path) -> None:
    pdf = tmp_path / "sample.pdf"
    _write_text_pdf(pdf, ["Abstract line about sensors."])

    phase1, full = extract_pdf_document(pdf)

    assert phase1.source_filename == "sample.pdf"
    assert phase1.document_type in {"text_based", "mixed"}
    assert len(phase1.pages) == 1
    assert phase1.extraction_quality.page_count == 1
    assert phase1.extraction_quality.extracted_character_count > 0
    assert phase1.raw_text
    assert full.structure is not None
    assert full.structure.semantic is not None


def test_phase1_scanned_like_pdf_kind(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    doc.close()

    raw = extract_text_layout(str(pdf))
    kind = classify_pdf_document_kind(raw)
    assert kind in {"scanned_image_based", "mixed"}

    phase1, _ = extract_pdf_document(pdf)
    assert phase1.document_type in {"scanned_image_based", "mixed"}
    assert phase1.extraction_quality.requires_ocr is True


def test_phase1_invalid_pdf(tmp_path: Path) -> None:
    bad = tmp_path / "not.pdf"
    bad.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(Phase1ExtractionError):
        extract_pdf_document(bad)
