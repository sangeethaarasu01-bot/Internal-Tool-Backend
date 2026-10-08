"""Re-extract tables inside caption-bounded regions."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.pipeline.table_extraction.borderless_grid import extract_borderless_grid
from app.pipeline.table_extraction.content_validate import validate_emitted_table_content
from app.pipeline.table_extraction.geometry import intersection_area
from app.pipeline.table_extraction.table_region import CaptionTableRegion, caption_bounded_region
from app.pipeline.table_extraction.types import CaptionInfo, PageIngest, RawDetectedTable


def _clip_raw_to_region(raw: RawDetectedTable, region: list[float]) -> RawDetectedTable:
    if len(region) < 4 or not raw.rows:
        return raw
    inter = intersection_area(raw.bbox, region)
    if inter <= 0:
        return raw
    n = len(raw.rows)
    full_h = max(1.0, raw.bbox[3] - raw.bbox[1])
    y0, y1 = region[1], region[3]
    sliced: list[list[str]] = []
    for i, row in enumerate(raw.rows):
        y = raw.bbox[1] + ((i + 0.5) / n) * full_h
        if y0 <= y <= y1:
            sliced.append(row)
    if len(sliced) < 2:
        sliced = raw.rows
    x0 = max(raw.bbox[0], region[0])
    x1 = min(raw.bbox[2], region[2])
    new_bbox = [x0, max(raw.bbox[1], y0), x1, min(raw.bbox[3], y1)]
    return RawDetectedTable(
        rows=sliced,
        bbox=new_bbox,
        engine=raw.engine,
        page_number=raw.page_number,
        bound_caption=raw.bound_caption,
    )


def raw_in_caption_region(
    pdf_path: Path,
    page: PageIngest,
    cap: CaptionInfo,
    caps_on_page: list[CaptionInfo],
    fallback: RawDetectedTable,
) -> tuple[RawDetectedTable, CaptionTableRegion]:
    meta = caption_bounded_region(cap, page, caps_on_page)
    fb = fallback.bbox
    if len(fb) >= 4 and fb[3] > fb[1]:
        search_bbox = [
            max(meta.bbox[0], fb[0] - 8),
            max(meta.bbox[1], fb[1] - 12),
            min(meta.bbox[2], fb[2] + 8),
            min(meta.bbox[3], fb[3] + 20),
        ]
    else:
        search_bbox = meta.bbox

    doc = pymupdf.open(str(pdf_path))
    try:
        pymupdf_page = doc[page.page_number - 1]
        rows, tight = extract_borderless_grid(
            pymupdf_page,
            search_bbox,
            caption_y_exclude=cap.bbox[1],
        )
    finally:
        doc.close()

    clipped = _clip_raw_to_region(fallback, meta.bbox)

    def _fill_score(grid: list[list[str]]) -> float:
        cells = [str(c or "").strip() for row in grid for c in row]
        if not cells:
            return 0.0
        return sum(1 for c in cells if c) / len(cells)

    ncol = max((len(r) for r in rows), default=0) if rows else 0
    borderless_fill = _fill_score(rows)
    borderless_ok = (
        len(rows) >= 2
        and ncol >= 2
        and len(rows) <= 15
        and borderless_fill >= 0.22
        and validate_emitted_table_content([], rows) is None
    )
    clipped_fill = _fill_score(clipped.rows)
    if borderless_ok and (
        borderless_fill > clipped_fill + 0.05
        or len(clipped.rows) > 12
        or clipped_fill < 0.2
    ):
        bbox = tight if len(tight) >= 4 else meta.bbox
        return (
            RawDetectedTable(
                rows=rows,
                bbox=bbox,
                engine="borderless-grid",
                page_number=page.page_number,
                bound_caption=cap.text.splitlines()[0].strip(),
            ),
            meta,
        )
    return clipped, meta


def borderless_only_in_region(
    pdf_path: Path,
    page: PageIngest,
    cap: CaptionInfo,
    caps_on_page: list[CaptionInfo],
    *,
    max_rows: int = 12,
) -> tuple[RawDetectedTable | None, CaptionTableRegion | None]:
    meta = caption_bounded_region(cap, page, caps_on_page)
    doc = pymupdf.open(str(pdf_path))
    try:
        pymupdf_page = doc[page.page_number - 1]
        rows, tight = extract_borderless_grid(
            pymupdf_page,
            meta.bbox,
            caption_y_exclude=cap.bbox[1],
        )
    finally:
        doc.close()
    ncol = max((len(r) for r in rows), default=0) if rows else 0
    if (
        len(rows) < 2
        or ncol < 2
        or len(rows) > max_rows
        or validate_emitted_table_content([], rows) is not None
    ):
        return None, meta
    bbox = tight if len(tight) >= 4 else meta.bbox
    return (
        RawDetectedTable(
            rows=rows,
            bbox=bbox,
            engine="borderless-grid",
            page_number=page.page_number,
            bound_caption=cap.text.splitlines()[0].strip(),
        ),
        meta,
    )
