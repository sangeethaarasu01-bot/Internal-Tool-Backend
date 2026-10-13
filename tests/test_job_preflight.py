from pathlib import Path

import pymupdf

from app.services.job_preflight import run_pdf_preflight
from app.services.text_extractor import PdfValidationError


def test_preflight_passes_minimal_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "one.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello IEEE article text for preflight.")
    doc.save(str(pdf_path))
    doc.close()

    report = run_pdf_preflight(pdf_path, file_size_bytes=pdf_path.stat().st_size)
    assert report.passed
    assert report.page_count == 1
    assert report.text_sample_chars > 10


def test_preflight_rejects_missing_file(tmp_path: Path) -> None:
    try:
        run_pdf_preflight(tmp_path / "missing.pdf", file_size_bytes=0)
        assert False, "expected PdfValidationError"
    except PdfValidationError:
        pass
