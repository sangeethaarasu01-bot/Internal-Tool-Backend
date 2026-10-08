"""Tests for caption-driven figure region matching and CLI figure output."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf
import pytest

from app.pipeline.phase1.captions import CaptionCandidate, collect_caption_candidates
from app.pipeline.phase1.figure_detection import (
    figure_caption_candidates,
    match_caption_to_region,
    render_region_png,
)
from app.pipeline.phase1.figures import extract_figures, _parse_figure_number
from app.pipeline.table_extraction.pipeline import run_extraction
from app.services.layout.document_pipeline import process_document_structure
from app.services.text_extractor import extract_text_layout

KAKICHI_PDF = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "pipeline_debug"
    / "access-kakichi-3657695-proof.pdf1"
    / "original.pdf"
)


def _expected_captioned_figure_count(pdf: Path) -> int:
    raw = extract_text_layout(str(pdf))
    structure = process_document_structure(raw, include_tagged_output=False)
    caps = collect_caption_candidates(structure.blocks)
    fig_caps = figure_caption_candidates(caps)
    used: set[int] = set()
    for cap in fig_caps:
        n = _parse_figure_number(cap.text)
        if n is not None:
            used.add(n)
    return len(used)


def test_match_figure_below_caption(tmp_path: Path) -> None:
    pdf = tmp_path / "fig.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=500, height=500)
    pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 160, 160), 1)
    pix.clear_with(200)
    page.insert_image(pymupdf.Rect(72, 120, 280, 320), pixmap=pix)
    page.insert_text((72, 360), "FIGURE 1. Sample diagram.", fontsize=11, fontname="helv")
    doc.save(pdf)
    doc.close()

    raw = extract_text_layout(str(pdf))
    structure = process_document_structure(raw, include_tagged_output=False)
    caps = collect_caption_candidates(structure.blocks)
    fig_caps = figure_caption_candidates(caps)
    assert len(fig_caps) == 1

    doc = pymupdf.open(str(pdf))
    page = doc[0]
    from app.pipeline.phase1.figure_detection import collect_figure_regions

    regions = collect_figure_regions(page)
    matched = match_caption_to_region(fig_caps[0], regions)
    assert matched is not None
    assert matched.region.bbox[3] < fig_caps[0].bbox[1]
    out = tmp_path / "fig1.png"
    assert render_region_png(page, matched.region.bbox, out)
    doc.close()

    out_dir = tmp_path / "assets"
    figures = extract_figures(pdf, raw, caps, figures_dir=out_dir, path_prefix="figures")
    assert len(figures) == 1
    assert figures[0].figure_id == "figure_1"
    assert figures[0].image_path == "figures/fig_1.png"
    assert (out_dir / "fig_1.png").is_file()
    assert figures[0].extraction_quality.image_extracted
    assert figures[0].figure_kind == "figure"


@pytest.mark.skipif(not KAKICHI_PDF.is_file(), reason="Reference PDF not present locally")
def test_kakichi_figure_output_paths_and_json(tmp_path: Path) -> None:
    output_json = tmp_path / "output_test.json"
    figures_dir = tmp_path / "figures"
    expected = _expected_captioned_figure_count(KAKICHI_PDF)
    assert expected >= 1

    data = run_extraction(
        KAKICHI_PDF,
        figures_dir=figures_dir,
        output_json=output_json,
    )

    png_files = sorted(figures_dir.glob("fig_*.png"))
    assert figures_dir.is_dir()
    assert len(png_files) == expected
    assert data.get("figure_count") == expected
    assert len(data.get("figures") or []) == expected

    for entry in data["figures"]:
        assert re.match(r"figure_\d+$", entry["figure_id"])
        m = re.search(r"fig_(\d+)\.png$", entry.get("image_path") or "")
        assert m is not None
        assert int(m.group(1)) == int(entry["figure_id"].split("_")[1])
        disk = tmp_path / entry["image_path"]
        assert disk.is_file()
        assert entry.get("caption")
        assert entry.get("figure_bbox")
        assert entry.get("extraction_engine")

    stems = {p.stem for p in png_files}
    assert "author" not in " ".join(stems).lower()
