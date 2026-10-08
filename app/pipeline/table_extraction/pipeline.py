"""Orchestrate generic academic PDF table extraction."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf

from app.pipeline.table_extraction.caption_match import match_table_caption
from app.pipeline.table_extraction.caption_regions import (
    EXTRACTION_ABOVE_CAPTION,
    caption_search_bbox,
    strict_table_captions,
)
from app.pipeline.table_extraction.cell_populate import enrich_raw_table_cells
from app.pipeline.table_extraction.content_validate import validate_emitted_table_content
from app.pipeline.table_extraction.region_refine import borderless_only_in_region, raw_in_caption_region
from app.pipeline.table_extraction.table_region import caption_bounded_region
from app.pipeline.table_extraction.dedup import dedup_one_per_caption, dedup_processed_tables
from app.pipeline.table_extraction.detection import detect_tables_on_page
from app.pipeline.table_extraction.geometry import intersection_area, iou
from app.pipeline.table_extraction.ingest import ingest_pdf
from app.pipeline.table_extraction.postprocess import postprocess_table, rows_to_raw_text, sanitize_rows
from app.pipeline.table_extraction.quality import score_candidate
from app.pipeline.table_extraction.types import CaptionInfo, PageIngest, ProcessedTable, RawDetectedTable
from app.pipeline.table_extraction.phase1_filter import passes_phase1_table_validation
from app.pipeline.table_extraction.validate import (
    cell_empty_ratio,
    extraction_confidence,
    is_phantom,
    validate_table,
)

logger = logging.getLogger(__name__)


def _same_column(a_bbox: list[float], b_bbox: list[float], page_width: float) -> bool:
    mid = page_width / 2.0
    ax = (a_bbox[0] + a_bbox[2]) / 2.0
    bx = (b_bbox[0] + b_bbox[2]) / 2.0
    return (ax < mid - 20 and bx < mid - 20) or (ax >= mid - 20 and bx >= mid - 20)


def _slice_raw_for_caption(
    raw: RawDetectedTable,
    cap: CaptionInfo,
    caps_on_page: list[CaptionInfo],
    page_width: float,
) -> RawDetectedTable:
    caps_col = [c for c in caps_on_page if _same_column(c.bbox, cap.bbox, page_width)]
    caps_col.sort(key=lambda c: c.bbox[1])
    idx = caps_col.index(cap) if cap in caps_col else 0
    table_above_caption = raw.bbox[3] < cap.bbox[1] + 20
    if table_above_caption:
        band_top = raw.bbox[1]
        band_bottom = min(raw.bbox[3], cap.bbox[1] - 2)
    else:
        band_top = max(raw.bbox[1], cap.bbox[3] + 2)
        band_bottom = (
            caps_col[idx + 1].bbox[1] - 2 if idx + 1 < len(caps_col) else raw.bbox[3]
        )
        band_bottom = min(band_bottom, raw.bbox[3])
    n = len(raw.rows)
    if n < 2:
        return raw
    full_h = max(1.0, raw.bbox[3] - raw.bbox[1])
    sliced_rows: list[list[str]] = []
    for i, row in enumerate(raw.rows):
        y = raw.bbox[1] + ((i + 0.5) / n) * full_h
        if band_top <= y <= band_bottom:
            sliced_rows.append(row)
    if len(sliced_rows) < 2 and len(caps_col) > 1:
        seg = max(2, n // len(caps_col))
        start = idx * seg
        sliced_rows = raw.rows[start : start + seg]
        band_top = raw.bbox[1] + (start / n) * full_h
        band_bottom = raw.bbox[1] + (min(n, start + seg) / n) * full_h
    if len(sliced_rows) < 2:
        sliced_rows = raw.rows
        band_top, band_bottom = raw.bbox[1], raw.bbox[3]
    new_bbox = [raw.bbox[0], band_top, raw.bbox[2], band_bottom]
    return RawDetectedTable(
        rows=sliced_rows,
        bbox=new_bbox,
        engine=raw.engine,
        page_number=raw.page_number,
        bound_caption=raw.bound_caption,
    )


def _bbox_overlaps_region(bbox: list[float], region: list[float]) -> bool:
    if len(bbox) < 4 or len(region) < 4:
        return False
    x0 = max(bbox[0], region[0])
    y0 = max(bbox[1], region[1])
    x1 = min(bbox[2], region[2])
    y1 = min(bbox[3], region[3])
    return x1 > x0 and y1 > y0


def _horizontal_overlap_with_region(bbox: list[float], region: list[float]) -> float:
    if len(bbox) < 4 or len(region) < 4:
        return 0.0
    left = max(bbox[0], region[0])
    right = min(bbox[2], region[2])
    width = max(1e-6, bbox[2] - bbox[0])
    return max(0.0, right - left) / width


def _caption_line_key(text: str | None) -> str:
    if not text:
        return ""
    return (text.splitlines() or [""])[0].strip().casefold()


def _table_has_content(tbl: ProcessedTable) -> bool:
    for cell in tbl.headers:
        if str(cell or "").strip():
            return True
    for row in tbl.rows:
        for cell in row:
            if str(cell or "").strip():
                return True
    return False


def _table_covers_caption(cap: CaptionInfo, emitted: list[ProcessedTable]) -> bool:
    cap_key = _caption_line_key(cap.text)
    if not cap_key:
        return False
    for tbl in emitted:
        if _caption_line_key(tbl.caption) == cap_key:
            return True
    return False


def _cap_for_caption_text(caps: list[CaptionInfo], caption_text: str | None) -> CaptionInfo | None:
    key = _caption_line_key(caption_text)
    if not key:
        return None
    for cap in caps:
        if _caption_line_key(cap.text) == key:
            return cap
    return None


def _region_dump_dict(
    table_id: str,
    page_number: int,
    region_meta,
    *,
    rows_after: int,
    cols_after: int,
    rows_removed: int,
    content_error: str | None = None,
) -> dict[str, Any]:
    return {
        "table_id": table_id,
        "page": page_number,
        "caption_bbox": region_meta.caption_bbox,
        "region_y_top": region_meta.region_y_top,
        "region_y_bottom": region_meta.region_y_bottom,
        "next_element_type": region_meta.next_element_type,
        "next_element_y0": region_meta.next_element_y0,
        "text_blocks_in_region": region_meta.text_blocks_in_region,
        "rows_after_clustering": rows_after,
        "columns_after_clustering": cols_after,
        "rows_removed_as_body_text": rows_removed,
        "final_rows": rows_after,
        "final_columns": cols_after,
        "content_validation_error": content_error,
    }


def _build_processed_table(
    page: PageIngest,
    raw: RawDetectedTable,
    *,
    table_index: int,
    pdf_path: Path,
    cap: CaptionInfo | None = None,
    force_partial: bool = False,
    extra_warnings: list[str] | None = None,
    rescue_mode: bool = False,
) -> tuple[ProcessedTable | None, dict[str, Any] | None]:
    caps_on_page = strict_table_captions(page)
    region_meta = None
    cap_bbox = list(cap.bbox) if cap is not None else None
    work_raw = raw
    if cap is not None and not rescue_mode:
        work_raw, region_meta = raw_in_caption_region(
            pdf_path, page, cap, caps_on_page, raw
        )
    elif cap is not None:
        region_meta = caption_bounded_region(cap, page, caps_on_page)

    work_raw = enrich_raw_table_cells(
        pdf_path,
        page,
        work_raw,
        caption_bbox=cap_bbox,
    )

    removed_body = 0
    if rescue_mode:
        headers, body_rows = [], sanitize_rows(work_raw.rows)
    else:
        bold_ratio = _bold_ratio_first_row(page, work_raw.bbox)
        headers, body_rows, removed_body = postprocess_table(
            work_raw.rows, first_row_bold_ratio=bold_ratio
        )
    if cap is not None:
        caption = (cap.text.splitlines() or [""])[0].strip()
        cap_conf = 0.9
        cap_found = True
    else:
        caption, cap_conf, cap_found = match_table_caption(
            page,
            work_raw.bbox,
            bound_caption=work_raw.bound_caption,
        )
    all_rows = ([headers] + body_rows) if headers else body_rows
    quality_score, _, _ = score_candidate(
        all_rows,
        work_raw.bbox,
        page,
        caption_nearby=cap_found,
        figure_regions=page.figure_regions,
    )
    content_err = validate_emitted_table_content(headers, body_rows)
    if cap is not None and not rescue_mode and content_err in {
        "prose_in_cell",
        "body_text_row",
        "too_many_rows",
    }:
        shrunk, region_meta = borderless_only_in_region(
            pdf_path, page, cap, caps_on_page, max_rows=14
        )
        if shrunk is not None:
            work_raw = enrich_raw_table_cells(
                pdf_path,
                page,
                shrunk,
                caption_bbox=cap_bbox,
            )
            headers, body_rows, removed_body = postprocess_table(work_raw.rows)
            content_err = validate_emitted_table_content(headers, body_rows)

    if content_err and cap is not None and not rescue_mode:
        work_raw, region_meta = raw_in_caption_region(
            pdf_path, page, cap, caps_on_page, work_raw
        )
        work_raw = enrich_raw_table_cells(
            pdf_path,
            page,
            work_raw,
            caption_bbox=cap_bbox,
        )
        headers, body_rows, removed_body = postprocess_table(work_raw.rows)
        content_err = validate_emitted_table_content(headers, body_rows)

    table_id = f"table_{table_index}"
    row_count = len(body_rows) + (1 if headers else 0)
    col_count = max(len(headers), max((len(r) for r in body_rows), default=0))
    dump = None
    if region_meta is not None:
        dump = _region_dump_dict(
            table_id,
            page.page_number,
            region_meta,
            rows_after=row_count,
            cols_after=col_count,
            rows_removed=removed_body,
            content_error=content_err,
        )
    if content_err:
        return None, dump

    status, _, warnings = validate_table(
        headers,
        body_rows,
        work_raw.bbox,
        page.figure_regions,
        page_height=page.page_height,
        page_width=page.page_width,
        caption_detected=cap_found,
        quality_score=quality_score,
    )
    if force_partial and status == "rejected":
        status = "partial"
        warnings = list(warnings) + ["caption_rescue"]
    if extra_warnings:
        warnings = list(warnings) + extra_warnings
    empty_r = cell_empty_ratio(all_rows)
    conf = extraction_confidence(
        status=status,
        engine=work_raw.engine,
        caption_detected=cap_found,
        empty_ratio=empty_r,
        quality_score=quality_score,
    )
    return (
        ProcessedTable(
            table_id=table_id,
            page_number=page.page_number,
            caption=caption,
            caption_confidence=round(cap_conf, 3),
            headers=headers,
            rows=body_rows,
            bbox=work_raw.bbox,
            engine=work_raw.engine,
            warnings=warnings,
            caption_detected=cap_found,
            status=status,
            reject_reason=None,
            confidence=conf,
        ),
        dump,
    )


def _rescue_rank(page: PageIngest, raw: RawDetectedTable, cap: CaptionInfo) -> float:
    below_gap = raw.bbox[1] - cap.bbox[3]
    above_gap = cap.bbox[1] - raw.bbox[3]
    span_contains_cap = raw.bbox[1] <= cap.bbox[1] and raw.bbox[3] >= cap.bbox[3]
    if not (
        span_contains_cap
        or (-40 <= below_gap <= 420)
        or (0 <= above_gap <= 220)
    ):
        return -1.0
    rows = sanitize_rows(raw.rows)
    nrows = len(rows)
    ncols = max(len(r) for r in rows) if rows else 0
    cells = [c for row in rows for c in row]
    fill = sum(1 for c in cells if str(c or "").strip()) / len(cells) if cells else 0.0
    score = fill * 20.0 + min(nrows, 30) * 0.5 + min(ncols, 10)
    if -8 <= below_gap <= 80:
        score += 5.0
    if 0 <= above_gap <= 120:
        score += 4.0
    score -= min(12.0, abs(below_gap) * 0.04 + abs(above_gap) * 0.04)
    if raw.engine == "img2table" and (raw.bbox[2] - raw.bbox[0]) > page.page_width * 0.55:
        score -= 10.0
    region = caption_search_bbox(cap, page, strict_table_captions(page))
    if _horizontal_overlap_with_region(raw.bbox, region) < 0.35:
        return -1.0
    engine_bonus = {
        "borderless-grid": 4.0,
        "camelot-lattice": 3.5,
        "img2table": 3.0,
        "pdfplumber": 2.5,
        "pymupdf": 2.0,
    }.get(raw.engine, 1.0)
    inter = intersection_area(raw.bbox, region)
    overlap = inter / max(1.0, (raw.bbox[2] - raw.bbox[0]) * (raw.bbox[3] - raw.bbox[1]))
    score += overlap * 12.0
    return score + engine_bonus


def _bold_ratio_first_row(page: PageIngest, bbox: list[float]) -> float:
    if len(bbox) < 4:
        return 0.0
    y0, y1 = bbox[1], bbox[1] + min(24.0, (bbox[3] - bbox[1]) * 0.15)
    bold = 0
    total = 0
    for block in page.blocks:
        if block.bbox[1] > y1 or block.bbox[3] < y0:
            continue
        total += 1
        if block.is_bold:
            bold += 1
    return bold / total if total else 0.0


def _draw_debug_overlays(debug_dir: Path, pdf_path: Path, tables: list[ProcessedTable]) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    by_page: dict[int, list[ProcessedTable]] = {}
    for t in tables:
        by_page.setdefault(t.page_number, []).append(t)
    for page_number, page_tables in by_page.items():
        page = doc[page_number - 1]
        for tbl in page_tables:
            if len(tbl.bbox) >= 4:
                rect = pymupdf.Rect(tbl.bbox)
                page.draw_rect(rect, color=(0, 0.8, 0), width=1.5)
        out = debug_dir / f"page_{page_number:04d}_tables.png"
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        pix.save(str(out))
    doc.close()


def run_extraction(
    pdf_path: Path,
    *,
    debug: bool = False,
    verbose: bool = False,
    debug_dir: Path | None = None,
    dump_regions: bool = False,
    dump_regions_dir: Path | None = None,
    figures_dir: Path | None = None,
    output_json: Path | None = None,
    extract_figures: bool = True,
) -> dict:
    if verbose:
        logging.basicConfig(level=logging.INFO)

    pdf_path = pdf_path.resolve()
    image_debug = debug_dir if debug else None
    pages = ingest_pdf(pdf_path, debug_dir=image_debug)

    emitted: list[ProcessedTable] = []
    phantom_dropped = 0
    phantom_reasons: dict[str, int] = {}
    debug_pages: list[dict[str, Any]] = []
    per_page_report: list[dict[str, Any]] = []
    caption_warnings: list[str] = []
    table_index = 0
    total_detected = 0
    engine_totals: dict[str, int] = {}
    region_dumps: list[dict[str, Any]] = []

    for page in pages:
        page_png = None
        if debug and debug_dir and page.png_path:
            page_png = Path(page.png_path)

        raw_tables, page_stats = detect_tables_on_page(
            pdf_path,
            page,
            verbose=verbose,
            page_png=page_png,
        )
        for eng, count in page_stats.engine_counts.items():
            engine_totals[eng] = engine_totals.get(eng, 0) + count

        page_debug: dict[str, Any] = {
            "page_number": page.page_number,
            "detection": page_stats.to_log_dict(),
            "candidates": [],
        }
        page_emitted: list[ProcessedTable] = []
        caps_on_page = strict_table_captions(page)

        for raw in raw_tables:
            total_detected += 1
            decision = "accept"
            drop_reason: str | None = None
            quality_score = 0.0

            _, _, cap_found = match_table_caption(
                page,
                raw.bbox,
                bound_caption=raw.bound_caption,
            )
            if is_phantom(raw.rows, raw.bbox) and not cap_found:
                decision = "phantom"
                drop_reason = "phantom_grid"
            else:
                bold_ratio = _bold_ratio_first_row(page, raw.bbox)
                caption, cap_conf, cap_found = match_table_caption(
                    page,
                    raw.bbox,
                    bound_caption=raw.bound_caption,
                )
                cap_obj = _cap_for_caption_text(caps_on_page, caption) if cap_found else None
                headers, body_rows, _ = postprocess_table(raw.rows, first_row_bold_ratio=bold_ratio)

                all_rows = ([headers] + body_rows) if headers else body_rows
                quality_score, _, _ = score_candidate(
                    all_rows,
                    raw.bbox,
                    page,
                    caption_nearby=cap_found,
                    figure_regions=page.figure_regions,
                )

                status, reject_reason, warnings = validate_table(
                    headers,
                    body_rows,
                    raw.bbox,
                    page.figure_regions,
                    page_height=page.page_height,
                    page_width=page.page_width,
                    caption_detected=cap_found,
                    quality_score=quality_score,
                )

                if status == "rejected" and not cap_found:
                    decision = "phantom"
                    drop_reason = reject_reason or "validation_failed"

                if decision == "accept":
                    if not cap_found:
                        decision = "phantom"
                        drop_reason = "no_caption_match"
                    if decision == "accept":
                        table_index += 1
                        built, dump = _build_processed_table(
                            page,
                            raw,
                            table_index=table_index,
                            pdf_path=pdf_path,
                            cap=cap_obj,
                        )
                        if built is None and cap_obj is not None:
                            built, dump = _build_processed_table(
                                page,
                                raw,
                                table_index=table_index,
                                pdf_path=pdf_path,
                                cap=cap_obj,
                                rescue_mode=True,
                                force_partial=True,
                            )
                        if built is None:
                            table_index -= 1
                            decision = "phantom"
                            drop_reason = "content_validation_failed"
                        elif not _table_has_content(built):
                            if cap_obj is not None:
                                shrunk, _ = borderless_only_in_region(
                                    pdf_path, page, cap_obj, caps_on_page
                                )
                                if shrunk is not None:
                                    built, dump = _build_processed_table(
                                        page,
                                        shrunk,
                                        table_index=table_index,
                                        pdf_path=pdf_path,
                                        cap=cap_obj,
                                    )
                                    if dump and dump_regions:
                                        region_dumps.append(dump)
                            if built is not None and _table_has_content(built):
                                page_emitted.append(built)
                            elif cap_found and built is not None:
                                built.warnings.append("empty_table_content")
                                page_emitted.append(built)
                            else:
                                table_index -= 1
                                decision = "phantom"
                                drop_reason = "empty_table_content"
                        else:
                            page_emitted.append(built)
                        if dump and dump_regions:
                            region_dumps.append(dump)

            if decision == "phantom":
                phantom_dropped += 1
                key = drop_reason or "unknown"
                phantom_reasons[key] = phantom_reasons.get(key, 0) + 1

            if debug:
                page_debug["candidates"].append(
                    {
                        "bbox": raw.bbox,
                        "engine": raw.engine,
                        "bound_caption": raw.bound_caption,
                        "decision": decision,
                        "reason": drop_reason,
                        "quality_score": quality_score,
                        "row_count": len(raw.rows),
                        "column_count": max(len(r) for r in raw.rows) if raw.rows else 0,
                    }
                )

        deduped_page = dedup_processed_tables(page_emitted)
        rescue_used_captions: set[str] = {
            _caption_line_key(t.caption) for t in deduped_page if t.caption
        }
        for cap in caps_on_page:
            if _table_covers_caption(cap, deduped_page):
                continue
            cap_key = _caption_line_key(cap.text)
            if cap_key in rescue_used_captions:
                continue
            region = caption_search_bbox(cap, page, caps_on_page)
            ranked_rescue: list[tuple[float, RawDetectedTable]] = []
            if not raw_tables:
                placeholder = RawDetectedTable(
                    rows=[["", ""], ["", ""]],
                    bbox=region,
                    engine="borderless-grid",
                    page_number=page.page_number,
                )
                fb, _ = raw_in_caption_region(
                    pdf_path, page, cap, caps_on_page, placeholder
                )
                ranked_rescue.append((1.0, fb))
            for raw in raw_tables:
                if not _bbox_overlaps_region(raw.bbox, region):
                    continue
                if _horizontal_overlap_with_region(raw.bbox, region) < 0.35:
                    continue
                rank = _rescue_rank(page, raw, cap)
                if rank >= 0:
                    ranked_rescue.append((rank, raw))
            ranked_rescue.sort(key=lambda t: t[0], reverse=True)
            rescued: ProcessedTable | None = None
            rescue_dump: dict[str, Any] | None = None
            for _rank, best_raw in ranked_rescue:
                candidate, dump = _build_processed_table(
                    page,
                    best_raw,
                    table_index=0,
                    pdf_path=pdf_path,
                    cap=cap,
                    force_partial=True,
                    extra_warnings=["caption_rescue"],
                )
                if candidate is not None:
                    rescued = candidate
                    rescue_dump = dump
                    break
            if rescued is None and ranked_rescue:
                fallback_raw, _ = raw_in_caption_region(
                    pdf_path, page, cap, caps_on_page, ranked_rescue[0][1]
                )
                rescued, rescue_dump = _build_processed_table(
                    page,
                    fallback_raw,
                    table_index=0,
                    pdf_path=pdf_path,
                    cap=cap,
                    force_partial=True,
                    extra_warnings=["caption_rescue"],
                    rescue_mode=True,
                )
            if rescued is not None:
                table_index += 1
                rescued.table_id = f"table_{table_index}"
                rescued.caption = (cap.text.splitlines() or [""])[0].strip()
                rescued.caption_detected = True
                deduped_page.append(rescued)
                rescue_used_captions.add(cap_key)
                if rescue_dump and dump_regions:
                    rescue_dump["table_id"] = rescued.table_id
                    region_dumps.append(rescue_dump)

        deduped_page = dedup_processed_tables(deduped_page)
        deduped_page = dedup_one_per_caption(deduped_page)

        def _caption_y(tbl: ProcessedTable) -> float:
            for cap in caps_on_page:
                if _caption_line_key(tbl.caption) == _caption_line_key(cap.text):
                    return cap.bbox[1]
            return tbl.bbox[1]

        deduped_page.sort(key=_caption_y)
        for tbl in deduped_page:
            emitted.append(tbl)

        for cap in caps_on_page:
            cap_line = (cap.text.splitlines() or [""])[0].strip()
            if not _table_covers_caption(cap, deduped_page):
                msg = (
                    f"Caption '{cap_line}' on page {page.page_number} has no emitted table "
                    f"(caption_bbox={cap.bbox})"
                )
                caption_warnings.append(msg)
                logger.warning(msg)

        per_page_report.append(
            {
                "page_number": page.page_number,
                "captions": len(caps_on_page),
                "candidates_from_detection": len(raw_tables),
                "emitted_before_dedup": len(page_emitted),
                "emitted": len(deduped_page),
                "caption_labels": [
                    (c.text.splitlines() or [""])[0].strip() for c in caps_on_page
                ],
            }
        )

        if debug:
            debug_pages.append(page_debug)

    emitted = [
        t
        for t in emitted
        if passes_phase1_table_validation(
            ([t.headers] + t.rows) if t.headers else t.rows,
            caption=t.caption,
            caption_detected=t.caption_detected,
        )
    ]

    tables_json = []
    for idx, t in enumerate(emitted, start=1):
        t.table_id = f"table_{idx}"
        row_count = len(t.rows) + (1 if t.headers else 0)
        col_count = max(len(t.headers), max((len(r) for r in t.rows), default=0))
        tables_json.append(
            {
                "table_id": t.table_id,
                "page_number": t.page_number,
                "caption": t.caption,
                "caption_confidence": t.caption_confidence,
                "headers": t.headers,
                "rows": t.rows,
                "row_count": row_count,
                "column_count": col_count,
                "bbox": t.bbox,
                "raw_text": rows_to_raw_text(t.headers, t.rows),
                "extraction_quality": {
                    "confidence": t.confidence,
                    "status": t.status,
                    "engine": t.engine,
                    "caption_detected": t.caption_detected,
                    "warnings": t.warnings,
                },
            }
        )

    result = {
        "source_pdf": pdf_path.name,
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "page_count": len(pages),
        "table_count": len(tables_json),
        "tables": tables_json,
        "extraction_summary": {
            "total_detected": total_detected,
            "total_emitted": len(tables_json),
            "total_rejected": phantom_dropped,
            "phantom_dropped": phantom_dropped,
            "rejected_reasons": phantom_reasons,
            "engine_candidate_counts": engine_totals,
            "per_page": per_page_report,
            "caption_warnings": caption_warnings,
        },
    }

    if debug and debug_dir:
        _draw_debug_overlays(debug_dir, pdf_path, emitted)
        audit_path = debug_dir / "detection_audit.json"
        audit_path.write_text(json.dumps({"pages": debug_pages}, indent=2), encoding="utf-8")
        result["debug_audit_path"] = str(audit_path)

    if dump_regions and region_dumps:
        out_dir = dump_regions_dir or (pdf_path.parent / "table_region_dumps")
        out_dir.mkdir(parents=True, exist_ok=True)
        for entry in region_dumps:
            tid = entry.get("table_id", "unknown")
            path = out_dir / f"{tid}_region.json"
            path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        result["region_dump_dir"] = str(out_dir)

    if extract_figures and figures_dir is not None and output_json is not None:
        from app.pipeline.phase1.figure_export import extract_figures_for_json

        figure_entries = extract_figures_for_json(
            pdf_path,
            figures_dir=figures_dir,
            output_json=output_json,
        )
        result["figure_count"] = len(figure_entries)
        result["figures"] = figure_entries
    else:
        result.setdefault("figure_count", 0)
        result.setdefault("figures", [])

    return result


def write_output(data: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def print_validation_report(data: dict) -> None:
    summary = data.get("extraction_summary", {})
    print("\n=== Table extraction validation report ===")
    print(f"Source: {data.get('source_pdf')}")
    print(f"Pages: {data.get('page_count')}")
    print(f"Tables emitted: {data.get('table_count')}")
    print(f"Figures emitted: {data.get('figure_count', 0)}")
    print(f"Candidates detected: {summary.get('total_detected')}")
    print(f"Phantom dropped (not emitted): {summary.get('phantom_dropped', 0)}")
    reasons = summary.get("rejected_reasons") or {}
    if reasons:
        print("Drop reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  - {reason}: {count}")
    engines = summary.get("engine_candidate_counts") or {}
    if engines:
        print("Engine raw candidate counts:")
        for eng, count in sorted(engines.items(), key=lambda x: -x[1]):
            print(f"  - {eng}: {count}")
    per_page = summary.get("per_page") or []
    if per_page:
        print("Per-page:")
        for row in per_page:
            labels = ", ".join(row.get("caption_labels") or []) or "—"
            print(
                f"  Page {row.get('page_number')}: captions={row.get('captions')}, "
                f"detected={row.get('candidates_from_detection')}, "
                f"emitted={row.get('emitted')} ({labels})"
            )
    cap_warn = summary.get("caption_warnings") or []
    if cap_warn:
        print("Caption coverage warnings:")
        for w in cap_warn:
            print(f"  - {w}")
    tables = data.get("tables") or []
    if tables:
        print("Content preview (first 2 rows):")
        for tbl in tables:
            caption = (tbl.get("caption") or tbl.get("table_id", ""))[:40]
            headers = tbl.get("headers") or []
            rows = tbl.get("rows") or []
            preview_rows: list[list[str]] = []
            if headers:
                preview_rows.append(headers)
            preview_rows.extend(rows[: max(0, 2 - len(preview_rows))])
            print(f"  {tbl.get('table_id')} ({caption}):")
            for row in preview_rows[:2]:
                print(f"    {' | '.join(str(c)[:80] for c in row)}")
    print("==========================================\n")
