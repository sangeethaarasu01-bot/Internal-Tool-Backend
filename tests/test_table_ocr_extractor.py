"""Tests for OCR table extraction fallback."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.services.layout.document_pipeline import process_document_structure
from app.services.table_extractor import extract_tables_from_page
from app.services.text_extractor import extract_text_layout

PDF_PATH = Path("uploads/20260907_132003_jsen-banerjeeroy-3639180-proof1.pdf")


@pytest.fixture(scope="module")
def rapidocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        pytest.skip("rapidocr-onnxruntime is not installed")
    return RapidOCR()


def test_ocr_extracts_table_ii_from_proof_pdf(rapidocr_engine) -> None:
    if not PDF_PATH.exists():
        pytest.skip("sample proof PDF is not available")

    doc = pymupdf.open(str(PDF_PATH))
    page = doc[3]
    blocks = extract_text_layout(str(PDF_PATH)).pages[3].blocks
    tables, ocr_applied = extract_tables_from_page(page, 4, blocks)
    doc.close()

    assert ocr_applied is True
    assert tables, "expected at least one OCR table on page 4"
    table_ii = next((table for table in tables if table.rows and table.rows[0][0] == "Sample"), None)
    assert table_ii is not None
    assert table_ii.rows[0][:4] == ["Sample", "TAN (mg/mL)", "TF (mg/mL)", "TH (mg/mL)"]
    assert table_ii.rows[1][0] == "S1"
    assert table_ii.rows[1][1] == "0.638"


def test_semantic_pipeline_renders_ocr_table(rapidocr_engine) -> None:
    if not PDF_PATH.exists():
        pytest.skip("sample proof PDF is not available")

    raw = extract_text_layout(str(PDF_PATH))
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert raw.document.ocr_applied is True
    assert "<table>" in sem.tagged_output
    assert "<th>Sample</th>" in sem.tagged_output
    assert "0.638</td>" in sem.tagged_output
    assert 'data-label="TABLE II"' in sem.tagged_output
