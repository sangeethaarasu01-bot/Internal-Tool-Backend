from __future__ import annotations

from pathlib import Path

import pymupdf

from app.pipeline.phase1.extract import extract_pdf_document
from app.pipeline.phase1.text_fidelity import scan_text_fidelity
from app.services.text_extractor import extract_text_layout
from app.utils.xml_text import strip_illegal_xml_chars


def _write_pdf_with_control_char(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    # Simulate math-font C0 placeholder bytes in extracted text.
    page.insert_text((72, 100), "Equation \x06t + Jopt", fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_scan_detects_control_chars_without_sanitizing_raw(tmp_path: Path) -> None:
    pdf = tmp_path / "math.pdf"
    _write_pdf_with_control_char(pdf)
    raw = extract_text_layout(str(pdf))
    report = scan_text_fidelity(raw)
    assert report.invalid_character_occurrences >= 1
    assert 0x6 in report.distinct_code_points
    assert report.characters_removed_for_xml >= 1
    raw_joined = report.raw_character_count
    norm = strip_illegal_xml_chars("Equation \x06t + Jopt")
    assert "\x06" not in norm
    assert raw_joined > report.normalized_character_count


def test_phase1_document_includes_raw_and_normalized(tmp_path: Path) -> None:
    pdf = tmp_path / "math.pdf"
    _write_pdf_with_control_char(pdf)
    phase1, _ = extract_pdf_document(pdf)
    assert "\x06" in phase1.raw_text or phase1.extraction_quality.invalid_character_report
    assert "\x06" not in phase1.normalized_text
    report = phase1.extraction_quality.invalid_character_report
    assert report is not None
    assert report.invalid_character_occurrences >= 1
