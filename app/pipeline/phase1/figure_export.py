"""Serialize Phase 1 figures for table-extraction CLI JSON output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from app.pipeline.phase1.captions import collect_caption_candidates
from app.pipeline.phase1.figure_detection import figure_caption_candidates
from app.pipeline.phase1.figures import extract_figures
from app.models.extracted_document import ExtractedFigure
from app.services.layout.document_pipeline import process_document_structure
from app.services.text_extractor import extract_text_layout

_ENGINE_LABEL = {
    "raster_image": "pymupdf_embedded",
    "layout_image_block": "pymupdf_layout_block",
    "vector_drawings": "pymupdf_vector_cluster",
    "whitespace_gap": "pymupdf_pixmap",
    "whitespace_zone": "pymupdf_pixmap",
    "caption_zone_render": "pymupdf_pixmap",
}


def default_figures_dir(output_json: Path) -> Path:
    """Default: sibling ``figures/`` next to the output JSON (e.g. ``data/figures``)."""
    return output_json.parent / "figures"


def figures_path_prefix(figures_dir: Path, json_parent: Path) -> str:
    figures_dir = figures_dir.resolve()
    json_parent = json_parent.resolve()
    try:
        return figures_dir.relative_to(json_parent).as_posix()
    except ValueError:
        return figures_dir.as_posix()


def _figure_number(figure: ExtractedFigure) -> int:
    from app.pipeline.phase1.caption_parse import parse_figure_number

    if figure.figure_number is not None:
        return figure.figure_number
    parsed = parse_figure_number(figure.caption)
    if parsed is not None:
        return parsed
    import re

    m2 = re.search(r"figure_(\d+)", figure.figure_id or "", re.IGNORECASE)
    return int(m2.group(1)) if m2 else 0


def _png_dimensions(path: Path) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0
    try:
        pix = pymupdf.Pixmap(str(path))
        return int(pix.width), int(pix.height)
    except Exception:
        return 0, 0


def serialize_figure_entry(
    figure: ExtractedFigure,
    *,
    json_parent: Path,
    caption_bbox: list[float] | None = None,
    extraction_engine: str = "pymupdf_pixmap",
) -> dict[str, Any]:
    fig_num = _figure_number(figure)
    stem = f"fig_{fig_num}" if fig_num else (figure.figure_id or "fig_unknown")
    image_path = figure.image_path
    if image_path and Path(image_path).is_absolute():
        try:
            image_path = Path(image_path).relative_to(json_parent).as_posix()
        except ValueError:
            image_path = str(image_path)
    abs_png = json_parent / image_path if image_path else None
    width, height = _png_dimensions(abs_png) if abs_png else (0, 0)
    if width == 0 and figure.bbox and len(figure.bbox) >= 4:
        from app.pipeline.phase1.figure_detection import RENDER_DPI

        scale = RENDER_DPI / 72.0
        width = int((figure.bbox[2] - figure.bbox[0]) * scale)
        height = int((figure.bbox[3] - figure.bbox[1]) * scale)

    return {
        "figure_id": f"figure_{fig_num}" if fig_num else figure.figure_id,
        "page_number": figure.page_number,
        "caption": figure.caption,
        "caption_bbox": caption_bbox or getattr(figure, "caption_bbox", None),
        "figure_bbox": figure.bbox,
        "image_path": image_path,
        "width": width,
        "height": height,
        "extraction_engine": extraction_engine,
    }


def extract_figures_for_json(
    pdf_path: Path,
    *,
    figures_dir: Path,
    output_json: Path,
) -> list[dict[str, Any]]:
    """Run caption-driven figure extraction and return JSON-ready figure records."""
    pdf_path = pdf_path.resolve()
    figures_dir.mkdir(parents=True, exist_ok=True)
    prefix = figures_path_prefix(figures_dir, output_json.parent)

    raw = extract_text_layout(str(pdf_path), original_filename=pdf_path.name)
    structure = process_document_structure(raw, include_tagged_output=False)
    caps = collect_caption_candidates(structure.blocks)

    extracted = extract_figures(
        pdf_path,
        raw,
        caps,
        figures_dir=figures_dir,
        path_prefix=prefix,
    )

    entries: list[dict[str, Any]] = []
    for fig in sorted(extracted, key=_figure_number):
        entries.append(
            serialize_figure_entry(
                fig,
                json_parent=output_json.parent,
                caption_bbox=fig.caption_bbox,
                extraction_engine=fig.extraction_engine or "pymupdf_pixmap",
            )
        )
    return entries
