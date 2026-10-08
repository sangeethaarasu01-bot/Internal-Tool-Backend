"""Step 1: PDF ingestion with PyMuPDF."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from app.pipeline.table_extraction.geometry import overlap_ratio_of_a
from app.pipeline.table_extraction.caption_regions import is_strict_table_caption_line
from app.pipeline.table_extraction.types import CaptionInfo, PageIngest, TextBlockInfo
FIGURE_CAPTION_PATTERN = re.compile(r"Fig(?:ure)?\.?\s+[IVX0-9]+[\.\:]", re.IGNORECASE)

_RENDER_DPI = 300


def _span_is_bold(flags: int) -> bool:
    # PyMuPDF: bit 4 (16) is bold in some versions; also check font name
    return bool(flags & 2**4)


def _blocks_from_page(page: pymupdf.Page) -> list[TextBlockInfo]:
    blocks: list[TextBlockInfo] = []
    data = page.get_text("dict")
    for block in data.get("blocks") or []:
        if block.get("type") != 0:
            continue
        lines_text: list[str] = []
        bold_chars = 0
        total_chars = 0
        bx0, by0, bx1, by1 = block.get("bbox", (0, 0, 0, 0))
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                t = span.get("text") or ""
                lines_text.append(t)
                total_chars += len(t)
                if _span_is_bold(int(span.get("flags") or 0)):
                    bold_chars += len(t)
        text = "\n".join(lines_text).strip()
        if not text:
            continue
        is_bold = total_chars > 0 and (bold_chars / total_chars) >= 0.5
        blocks.append(
            TextBlockInfo(
                text=text,
                bbox=[float(bx0), float(by0), float(bx1), float(by1)],
                is_bold=is_bold,
            )
        )
    return blocks


def _line_starts_caption(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    if is_strict_table_caption_line(stripped):
        return ("table", stripped)
    if FIGURE_CAPTION_PATTERN.search(stripped):
        return ("figure", stripped)
    return None


def _caption_from_block(block: TextBlockInfo) -> CaptionInfo | None:
    lines = block.text.splitlines()
    if not lines:
        return None
    first = lines[0]
    hit = _line_starts_caption(first)
    if not hit:
        return None
    caption_type, _ = hit
    parts = [first.strip()]
    for line in lines[1:]:
        if not line.strip():
            break
        parts.append(line.strip())
    return CaptionInfo(
        text="\n".join(parts),
        bbox=list(block.bbox),
        caption_type=caption_type,  # type: ignore[arg-type]
    )


def _figure_regions(page: pymupdf.Page, captions: list[CaptionInfo]) -> list[list[float]]:
    regions: list[list[float]] = []
    for cap in captions:
        if cap.caption_type == "figure":
            regions.append(list(cap.bbox))
    return regions


def ingest_pdf(
    pdf_path: Path,
    *,
    debug_dir: Path | None = None,
) -> list[PageIngest]:
    doc = pymupdf.open(str(pdf_path))
    pages: list[PageIngest] = []
    matrix = pymupdf.Matrix(_RENDER_DPI / 72.0, _RENDER_DPI / 72.0)

    for index in range(doc.page_count):
        page = doc[index]
        page_number = index + 1
        rect = page.rect
        blocks = _blocks_from_page(page)
        captions: list[CaptionInfo] = []
        for block in blocks:
            cap = _caption_from_block(block)
            if cap:
                captions.append(cap)

        png_path: str | None = None
        image_width = image_height = 0
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_path = str(debug_dir / f"page_{page_number:04d}.png")
            pix.save(png_path)
            image_width, image_height = pix.width, pix.height
        else:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_width, image_height = pix.width, pix.height
            if debug_dir is None:
                # Still need dimensions for img2table; write to temp only when detecting
                pass

        figure_regions = _figure_regions(page, captions)

        pages.append(
            PageIngest(
                page_number=page_number,
                page_width=float(rect.width),
                page_height=float(rect.height),
                raw_text=page.get_text("text") or "",
                blocks=blocks,
                captions=captions,
                figure_regions=figure_regions,
                png_path=png_path,
                image_width=image_width,
                image_height=image_height,
            )
        )

    doc.close()
    return pages


def render_page_png(page: pymupdf.Page, dest: Path) -> tuple[int, int]:
    matrix = pymupdf.Matrix(_RENDER_DPI / 72.0, _RENDER_DPI / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(dest))
    return pix.width, pix.height


def table_overlaps_figure(
    table_bbox: list[float],
    figure_regions: list[list[float]],
    threshold: float = 0.3,
) -> bool:
    for region in figure_regions:
        if overlap_ratio_of_a(table_bbox, region) > threshold:
            return True
    return False
