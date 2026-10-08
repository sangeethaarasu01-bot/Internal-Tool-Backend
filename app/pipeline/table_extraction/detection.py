"""Multi-engine table detection with merged search regions."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from app.pipeline.table_extraction.borderless_grid import extract_borderless_grid
from app.pipeline.table_extraction.cell_populate import cell_fill_ratio
from app.pipeline.table_extraction.caption_regions import caption_search_bbox, strict_table_captions
from app.pipeline.table_extraction.caption_match import match_table_caption
from app.pipeline.table_extraction.dedup import merge_raw_candidates
from app.pipeline.table_extraction.geometry import (
    bbox_area,
    camelot_bbox_to_fitz,
    fitz_bbox_to_camelot_area,
    image_bbox_to_fitz,
    iou,
)
from app.pipeline.table_extraction.ingest import render_page_png, table_overlaps_figure
from app.pipeline.table_extraction.ocr_grid import ocr_bbox_to_grid
from app.pipeline.table_extraction.postprocess import sanitize_rows
from app.pipeline.table_extraction.quality import score_candidate
from app.pipeline.table_extraction.search_regions import build_search_regions
from app.pipeline.table_extraction.stream_filters import stream_candidate_reject_reason
from app.pipeline.table_extraction.types import EngineName, PageIngest, RawDetectedTable

logger = logging.getLogger(__name__)

MIN_ROWS = 2
MIN_COLS = 2


@dataclass
class PageDetectionStats:
    page_number: int
    caption_count: int = 0
    engine_counts: dict[str, int] = field(default_factory=dict)
    candidates_before_merge: int = 0
    candidates_after_merge: int = 0
    rejected_by_quality: int = 0
    emitted_from_detection: int = 0

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "captions": self.caption_count,
            "camelot-lattice": self.engine_counts.get("camelot-lattice", 0),
            "camelot-stream": self.engine_counts.get("camelot-stream", 0),
            "img2table": self.engine_counts.get("img2table", 0),
            "pymupdf": self.engine_counts.get("pymupdf", 0),
            "pdfplumber": self.engine_counts.get("pdfplumber", 0),
            "borderless-grid": self.engine_counts.get("borderless-grid", 0),
            "ocr-grid": self.engine_counts.get("ocr-grid", 0),
            "candidates_before_merge": self.candidates_before_merge,
            "candidates_after_merge": self.candidates_after_merge,
            "rejected": self.rejected_by_quality,
            "emitted": self.emitted_from_detection,
        }


def _cell_stats(rows: list[list[str]]) -> tuple[int, int, float]:
    rows = sanitize_rows(rows)
    if not rows:
        return 0, 0, 0.0
    nrows = len(rows)
    ncols = max(len(r) for r in rows)
    total = nrows * ncols
    nonempty = sum(1 for row in rows for cell in row if (cell or "").strip())
    return nrows, ncols, nonempty / total if total else 0.0


def _normalize_rows(rows: list[list[str]]) -> list[list[str]]:
    rows = sanitize_rows(rows)
    if not rows:
        return []
    ncols = max(len(r) for r in rows)
    return [list(row) + [""] * (ncols - len(row)) for row in rows]


def _minimal_shape(rows: list[list[str]]) -> bool:
    rows = _normalize_rows(rows)
    nrows, ncols, _ = _cell_stats(rows)
    return nrows >= MIN_ROWS and ncols >= MIN_COLS


def _bbox_in_region(bbox: list[float], region: list[float]) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def _record_engine(stats: PageDetectionStats, engine: str, count: int = 1) -> None:
    stats.engine_counts[engine] = stats.engine_counts.get(engine, 0) + count


def _append_candidate(
    bucket: list[RawDetectedTable],
    rows: list[list[str]],
    bbox: list[float],
    engine: EngineName,
    page_number: int,
    stats: PageDetectionStats,
) -> None:
    if not _minimal_shape(rows):
        return
    bucket.append(
        RawDetectedTable(
            rows=_normalize_rows(rows),
            bbox=bbox,
            engine=engine,
            page_number=page_number,
        )
    )
    _record_engine(stats, engine)


def _camelot_in_area(
    pdf_path: Path,
    page_number: int,
    page_height: float,
    area_bbox: list[float],
    flavor: str,
    stats: PageDetectionStats,
) -> list[RawDetectedTable]:
    import camelot

    flavor_name: EngineName = "camelot-lattice" if flavor == "lattice" else "camelot-stream"
    area = fitz_bbox_to_camelot_area(area_bbox, page_height)
    kwargs: dict = {"flavor": flavor, "pages": str(page_number), "table_areas": [area]}
    if flavor == "lattice":
        kwargs.update({"line_scale": 40, "line_tol": 2, "joint_tol": 2})
    else:
        kwargs.update({"edge_tol": 50, "row_tol": 10, "column_tol": 10})

    try:
        tables = camelot.read_pdf(str(pdf_path), **kwargs)
    except Exception as exc:
        logger.debug("Camelot %s failed page %s: %s", flavor, page_number, exc)
        return []

    out: list[RawDetectedTable] = []
    for table in tables:
        rows = [[str(v) for v in row] for row in table.df.values.tolist()]
        if not _minimal_shape(rows):
            continue
        bbox = camelot_bbox_to_fitz(table._bbox, page_height)
        if not _bbox_in_region(bbox, area_bbox):
            continue
        if flavor == "stream":
            reason = stream_candidate_reject_reason(
                rows,
                bbox,
                page_height=page_height,
                caption_found=False,
            )
            if reason:
                continue
        out.append(
            RawDetectedTable(rows=_normalize_rows(rows), bbox=bbox, engine=flavor_name, page_number=page_number)
        )
        _record_engine(stats, flavor_name)
    return out


def _pymupdf_in_area(
    pymupdf_page: pymupdf.Page,
    area_bbox: list[float],
    page_number: int,
    stats: PageDetectionStats,
) -> list[RawDetectedTable]:
    detected: list[RawDetectedTable] = []
    clip = pymupdf.Rect(area_bbox)
    for strategy in (None, "lines", "lines_strict"):
        try:
            finder = (
                pymupdf_page.find_tables(strategy=strategy, clip=clip)
                if strategy
                else pymupdf_page.find_tables(clip=clip)
            )
            raw_tables = finder.tables if finder else []
        except Exception:
            continue
        for table in raw_tables:
            data = table.extract() or []
            rows = [[" ".join(str(c or "").split()) for c in row] for row in data if row]
            if not _minimal_shape(rows):
                continue
            rect = table.bbox
            bbox = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
            detected.append(
                RawDetectedTable(rows=_normalize_rows(rows), bbox=bbox, engine="pymupdf", page_number=page_number)
            )
            _record_engine(stats, "pymupdf")
    return detected


def _img2table_page(png_path: Path, page: PageIngest, stats: PageDetectionStats) -> list[RawDetectedTable]:
    try:
        from img2table.document import Image as Img2TableImage
    except ImportError:
        return []
    try:
        extracted = Img2TableImage(str(png_path)).extract_tables(borderless_tables=True)
    except Exception as exc:
        logger.debug("img2table failed page %s: %s", page.page_number, exc)
        return []

    table_list: list = []
    if isinstance(extracted, dict):
        for value in extracted.values():
            table_list.extend(value or [])
    elif extracted:
        table_list = list(extracted)

    detected: list[RawDetectedTable] = []
    for tbl in table_list:
        try:
            rows = [[str(v) for v in row] for row in tbl.df.values.tolist()]
        except Exception:
            continue
        if not _minimal_shape(rows):
            continue
        bb = tbl.bbox
        bbox = image_bbox_to_fitz(
            (bb.x1, bb.y1, bb.x2, bb.y2),
            page.page_width,
            page.page_height,
            page.image_width,
            page.image_height,
        )
        detected.append(
            RawDetectedTable(
                rows=_normalize_rows(rows),
                bbox=bbox,
                engine="img2table",
                page_number=page.page_number,
            )
        )
        _record_engine(stats, "img2table")
    return detected


_PDFPLUMBER_TEXT_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "intersection_tolerance": 5,
    "min_words_vertical": 2,
    "min_words_horizontal": 1,
}


def _pdfplumber_extract_rows(crop) -> list[list[list[str]]]:
    """Default line-based tables, then text-alignment strategy for borderless grids."""
    batches: list[list[list[str]]] = []
    for raw in crop.extract_tables() or []:
        rows = [[str(c or "") for c in row] for row in raw if row]
        if _minimal_shape(rows):
            batches.append(_normalize_rows(rows))
    if batches:
        return batches
    for raw in crop.extract_tables(table_settings=_PDFPLUMBER_TEXT_TABLE_SETTINGS) or []:
        rows = [[str(c or "") for c in row] for row in raw if row]
        if _minimal_shape(rows):
            batches.append(_normalize_rows(rows))
    return batches


def _pdfplumber_in_area(
    pdf_path: Path,
    page_number: int,
    area_bbox: list[float],
    stats: PageDetectionStats,
) -> list[RawDetectedTable]:
    try:
        import pdfplumber
    except ImportError:
        return []

    detected: list[RawDetectedTable] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return []
            page = pdf.pages[page_number - 1]
            x0, y0, x1, y1 = area_bbox
            crop = page.crop((x0, y0, x1, y1))
            for rows in _pdfplumber_extract_rows(crop):
                detected.append(
                    RawDetectedTable(
                        rows=rows,
                        bbox=[x0, y0, x1, y1],
                        engine="pdfplumber",
                        page_number=page_number,
                    )
                )
                _record_engine(stats, "pdfplumber")
    except Exception as exc:
        logger.debug("pdfplumber failed page %s: %s", page_number, exc)
    return detected


def _region_hints_table_caption(page: PageIngest, region: list[float]) -> bool:
    caps = strict_table_captions(page)
    for cap in caps:
        hint = caption_search_bbox(cap, page, caps)
        if iou(region, hint) > 0.15 or _bbox_in_region(cap.bbox, region):
            return True
    return False


def _engines_for_region(
    pdf_path: Path,
    page: PageIngest,
    region: list[float],
    pymupdf_page: pymupdf.Page,
    png_path: Path | None,
    stats: PageDetectionStats,
) -> list[RawDetectedTable]:
    found: list[RawDetectedTable] = []
    pn = page.page_number

    lattice = _camelot_in_area(pdf_path, pn, page.page_height, region, "lattice", stats)
    found.extend(lattice)

    if not lattice:
        found.extend(_camelot_in_area(pdf_path, pn, page.page_height, region, "stream", stats))

    grid_rows, grid_bbox = extract_borderless_grid(pymupdf_page, region)
    if _minimal_shape(grid_rows):
        _append_candidate(found, grid_rows, grid_bbox, "borderless-grid", pn, stats)

    found.extend(_pymupdf_in_area(pymupdf_page, region, pn, stats))
    found.extend(_pdfplumber_in_area(pdf_path, pn, region, stats))

    region_fill = max((cell_fill_ratio(c.rows) for c in found), default=0.0)
    if _region_hints_table_caption(page, region) and (
        not found or region_fill < 0.18
    ):
        ocr_rows, ocr_bbox = ocr_bbox_to_grid(pymupdf_page, region)
        if len(ocr_rows) <= 22 and _minimal_shape(ocr_rows):
            _append_candidate(found, ocr_rows, ocr_bbox, "ocr-grid", pn, stats)

    return found


def detect_tables_on_page(
    pdf_path: Path,
    page: PageIngest,
    *,
    use_pdfplumber: bool = True,
    verbose: bool = False,
    page_png: Path | None = None,
) -> tuple[list[RawDetectedTable], PageDetectionStats]:
    page_number = page.page_number
    stats = PageDetectionStats(page_number=page_number, caption_count=len(strict_table_captions(page)))

    doc = pymupdf.open(str(pdf_path))
    pymupdf_page = doc[page_number - 1]

    png_path = page_png
    if png_path is None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            png_path = Path(tmp.name)
        w, h = render_page_png(pymupdf_page, png_path)
        page.image_width, page.image_height = w, h

    regions = build_search_regions(page)
    if not regions:
        regions = [[36, 36, page.page_width - 36, page.page_height - 36]]

    all_candidates: list[RawDetectedTable] = []

    def _caption_near(bbox: list[float]) -> bool:
        for cap in strict_table_captions(page):
            cy = (cap.bbox[1] + cap.bbox[3]) / 2
            ty = (bbox[1] + bbox[3]) / 2
            if abs(cy - ty) < 120:
                return True
        return False

    for region in regions:
        all_candidates.extend(_engines_for_region(pdf_path, page, region, pymupdf_page, png_path, stats))

    if png_path and png_path.is_file():
        img_tables = _img2table_page(png_path, page, stats)
        for raw in img_tables:
            if not any(iou(raw.bbox, c.bbox) > 0.30 for c in all_candidates):
                all_candidates.append(raw)

    doc.close()
    stats.candidates_before_merge = len(all_candidates)

    def _caption_text(bbox: list[float]) -> str | None:
        text, _, found = match_table_caption(page, bbox)
        return text if found else None

    merged = merge_raw_candidates(
        all_candidates,
        page,
        _caption_near,
        caption_for_bbox_fn=_caption_text,
    )
    stats.candidates_after_merge = len(merged)
    stats.rejected_by_quality = max(0, stats.candidates_before_merge - len(merged))

    filtered: list[RawDetectedTable] = []
    for tbl in merged:
        cap_near = _caption_near(tbl.bbox)
        _, _, hard_reject = score_candidate(
            tbl.rows,
            tbl.bbox,
            page,
            caption_nearby=cap_near,
            figure_regions=page.figure_regions,
        )
        if hard_reject in {"bbox_covers_page", "bbox_too_small", "column_count_too_high"}:
            stats.rejected_by_quality += 1
            continue
        if table_overlaps_figure(tbl.bbox, page.figure_regions, threshold=0.55):
            stats.rejected_by_quality += 1
            continue
        filtered.append(tbl)

    stats.emitted_from_detection = len(filtered)

    if verbose:
        d = stats.to_log_dict()
        logger.info(
            "Page %s: captions=%s lattice=%s stream=%s img2table=%s pymupdf=%s pdfplumber=%s "
            "borderless=%s ocr=%s before_merge=%s after_merge=%s rejected=%s emitted=%s",
            page_number,
            d["captions"],
            d["camelot-lattice"],
            d["camelot-stream"],
            d["img2table"],
            d["pymupdf"],
            d["pdfplumber"],
            d["borderless-grid"],
            d["ocr-grid"],
            d["candidates_before_merge"],
            d["candidates_after_merge"],
            d["rejected"],
            d["emitted"],
        )

    return filtered, stats
