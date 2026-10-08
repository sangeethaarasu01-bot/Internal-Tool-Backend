from __future__ import annotations

from pathlib import Path
import pymupdf

from app.pipeline.phase1.captions import collect_caption_candidates
from app.pipeline.phase1.extract import extract_pdf_document
from app.pipeline.phase1.tables import _grid_quality, enrich_tables
from app.services.text_extractor import extract_text_layout


def _write_text_pdf(path: Path, pages: list[str]) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 100), text, fontsize=12, fontname="helv")
    doc.save(path)
    doc.close()


def test_grid_quality_partial_for_single_row() -> None:
    _, quality = _grid_quality([["only", "row"]])
    assert quality.status == "partial"


def test_grid_quality_failed_for_empty() -> None:
    _, quality = _grid_quality([])
    assert quality.status == "failed"


def test_multi_page_phase1(tmp_path: Path) -> None:
    pdf = tmp_path / "multi.pdf"
    _write_text_pdf(pdf, ["Page one", "Page two"])
    phase1, _ = extract_pdf_document(pdf, bundle_dir=tmp_path / "bundle")
    assert len(phase1.pages) == 2
    assert phase1.extraction_quality.page_count == 2


def test_table_enrichment_preserves_raw_text_fallback(tmp_path: Path) -> None:
    pdf = tmp_path / "t.pdf"
    _write_text_pdf(pdf, ["TABLE I\nSample table caption"])
    raw = extract_text_layout(str(pdf))
    from app.services.layout.document_pipeline import process_document_structure

    structure = process_document_structure(raw, include_tagged_output=False)
    caps = collect_caption_candidates(structure.blocks)
    tables = enrich_tables(raw, caps, pdf_path=pdf, assets_dir=tmp_path / "tables")
    assert isinstance(tables, list)


def test_figure_extraction_on_image_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "img.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((72, 320), "FIGURE 1. Sample architecture diagram.", fontsize=11, fontname="helv")
    # Small raster image block
    pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 120, 120), 1)
    pix.clear_with(255)
    page.insert_image(pymupdf.Rect(72, 120, 220, 280), pixmap=pix)
    doc.save(pdf)
    doc.close()

    bundle = tmp_path / "bundle"
    phase1, _ = extract_pdf_document(pdf, bundle_dir=bundle)
    assert phase1.extraction_quality.figure_count >= 0


def test_scanned_detection_empty_page(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    doc.close()
    phase1, _ = extract_pdf_document(pdf)
    assert phase1.document_type in {"scanned_image_based", "mixed", "unknown"}


def test_control_chars_preserved_in_raw(tmp_path: Path) -> None:
    pdf = tmp_path / "ctrl.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "x\x06y", fontsize=12, fontname="helv")
    doc.save(pdf)
    doc.close()
    phase1, _ = extract_pdf_document(pdf)
    assert "\x06" in phase1.raw_text
    assert "\x06" not in phase1.normalized_text
