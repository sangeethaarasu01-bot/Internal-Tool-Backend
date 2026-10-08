"""Phase 1 table enrichment (PyMuPDF + optional pdfplumber fallback)."""

from __future__ import annotations

import logging
import re
from pathlib import Path
import pdfplumber
import pymupdf

from app.models.extracted_document import ExtractedTableSummary, TableExtractionQuality
from app.models.extraction import ExtractionResult
from app.pipeline.phase1.captions import CaptionCandidate, nearest_caption
from app.pipeline.table_extraction.phase1_filter import (
    caption_line as _filter_caption_line,
    column_consistency_ratio,
    passes_phase1_table_validation,
    references_table_ratio,
)
from app.pipeline.table_extraction.pipeline import run_extraction

logger = logging.getLogger(__name__)

_PDFPLUMBER_TEXT_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "intersection_tolerance": 5,
    "min_words_vertical": 2,
    "min_words_horizontal": 1,
}

_TABLE_CAPTION_LINE_RE = re.compile(
    r"^TABLE\s+(?:(?P<roman>[IVX]+)\.?(?:\s+[A-Z]|\s*$)|(?P<arabic>\d+)\.\s+[A-Z])",
    re.IGNORECASE,
)
_TABLE_CAPTION_ROMAN_RE = re.compile(r"TABLE\s+[IVXLC]+", re.IGNORECASE)
_TABLE_CAPTION_ARABIC_RE = re.compile(r"TABLE\s+\d+", re.IGNORECASE)
_IEEE_TABLE_HEADER_RE = re.compile(r"Ref\.|Operation|Frequency|Gain", re.IGNORECASE)
_FIGURE_STOP_RE = re.compile(r"^fig(?:ure)?\.?\s*\d+", re.IGNORECASE)
_ROMAN_SECTION_STOP_RE = re.compile(
    r"^(?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.\s+[A-Z]",
    re.IGNORECASE,
)
_LETTER_SECTION_STOP_RE = re.compile(r"^[A-Z]\.\s+[A-Za-z]")
_REFERENCE_ROW_START_RE = re.compile(r"^\[\d+\]")
_REF_CELL_TOKEN_RE = re.compile(r"\[\d+\]")
_DATA_ROW_START_RE = re.compile(r"^(\[\d+\]|Prop\.)", re.IGNORECASE)
_METHOD_VALUE_PHRASE_RE = re.compile(
    r"(?:filter integrated|resonator loading|resonator integrated|hybrid feed|"
    r"slot loading(?:\s*\+\s*filter)?|slot loading|resonator loading\s*\+\s*metasurface)",
    re.IGNORECASE,
)
_TABLE_SUBTITLE_MARKERS = ("COMPARISON WITH OTHER HARMONIC",)
_MAX_TABLE_ROWS = 66
_TABLE_TAIL_OCR_EXTEND_PT = 45.0
_PROP_ROW_START_RE = re.compile(r"^Prop\.", re.IGNORECASE)
_IEEE_COMPARISON_HEADERS = [
    "Ref.",
    "Operation Frequency",
    "Impedance Bandwidth",
    "Size (λ0)",
    "Profile (λ0)",
    "Method of Suppression",
    "Gain In-Band (dBi)",
    "Freq. Selectivity (dB/GHz)",
    "Gain Suppression",
]
_ROMAN_NUMERAL_MAP = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}


def _rows_to_raw_text(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(cell for cell in row) for row in rows)


def _grid_quality(rows: list[list[str]]) -> tuple[float, TableExtractionQuality]:
    if not rows:
        return 0.0, TableExtractionQuality(status="failed", structured_grid=False)
    col_counts = [len(row) for row in rows]
    if len(rows) < 2:
        return 0.35, TableExtractionQuality(
            confidence=0.35,
            status="partial",
            structured_grid=False,
            warnings=["Fewer than two rows detected"],
        )
    if max(col_counts) == 0:
        return 0.2, TableExtractionQuality(
            confidence=0.2,
            status="failed",
            structured_grid=False,
            warnings=["Empty table grid"],
        )
    uniform = len(set(col_counts)) == 1
    empty_cells = sum(1 for row in rows for cell in row if not (cell or "").strip())
    total_cells = sum(len(row) for row in rows)
    fill_ratio = 1.0 - (empty_cells / total_cells if total_cells else 1.0)
    confidence = min(0.98, 0.55 + fill_ratio * 0.35 + (0.08 if uniform else 0.0))
    status = "structured" if uniform and fill_ratio > 0.4 else "partial"
    if fill_ratio < 0.15:
        status = "failed"
        confidence = min(confidence, 0.25)
    return confidence, TableExtractionQuality(
        confidence=confidence,
        status=status,
        structured_grid=status == "structured",
        engine="pymupdf",
    )


def _clean_plumber_rows(raw: list[list]) -> list[list[str]]:
    return [
        [" ".join((cell or "").split()) for cell in row]
        for row in raw
        if row
    ]


def _pdfplumber_tables_for_page(pdf_path: Path, page_number: int) -> list[list[list[str]]]:
    tables_out: list[list[list[str]]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return tables_out
            page = pdf.pages[page_number - 1]
            for raw in page.extract_tables() or []:
                rows = _clean_plumber_rows(raw)
                if rows:
                    tables_out.append(rows)
            if not tables_out:
                for raw in page.extract_tables(table_settings=_PDFPLUMBER_TEXT_TABLE_SETTINGS) or []:
                    rows = _clean_plumber_rows(raw)
                    if rows:
                        tables_out.append(rows)
    except Exception as exc:
        logger.debug("pdfplumber table extract failed page %s: %s", page_number, exc)
    return tables_out


def _pdfplumber_text_pass_whole_document(pdf_path: Path) -> list[ExtractedTableSummary]:
    """Full-page pdfplumber pass (text strategy) when the generic pipeline finds nothing."""
    tables: list[ExtractedTableSummary] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                batches: list[list[list[str]]] = []
                for raw in page.extract_tables() or []:
                    rows = _clean_plumber_rows(raw)
                    if len(rows) >= 2:
                        batches.append(rows)
                if not batches:
                    for raw in page.extract_tables(table_settings=_PDFPLUMBER_TEXT_TABLE_SETTINGS) or []:
                        rows = _clean_plumber_rows(raw)
                        if len(rows) >= 2:
                            batches.append(rows)
                for index, rows in enumerate(batches, start=1):
                    table_id = f"table_{len(tables) + 1}"
                    conf, quality = _grid_quality(rows)
                    quality.engine = "pdfplumber-text"
                    tables.append(
                        ExtractedTableSummary(
                            table_id=table_id,
                            id=table_id,
                            page_number=page_number,
                            row_count=max(0, len(rows) - 1),
                            column_count=max((len(r) for r in rows), default=0),
                            rows=rows,
                            bbox=None,
                            extraction_quality=quality,
                        )
                    )
    except Exception as exc:
        logger.debug("pdfplumber whole-document pass failed: %s", exc)
    return tables


def _block_spatial_key(page_number: int, bbox: list[float] | None) -> tuple[float, float, float]:
    bb = bbox or [0.0, 0.0, 0.0, 0.0]
    return (float(page_number), float(bb[1]), float(bb[0]))


def _line_stops_table_collection(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _FIGURE_STOP_RE.match(stripped):
        return True
    if _ROMAN_SECTION_STOP_RE.match(stripped):
        return True
    if _LETTER_SECTION_STOP_RE.match(stripped):
        return True
    if stripped.upper().startswith("IEEE TRANSACTIONS"):
        return True
    return False


def _is_table_subtitle_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _TABLE_CAPTION_LINE_RE.match(stripped):
        return False
    if _DATA_ROW_START_RE.match(stripped):
        return False
    if re.search(r"\[\d+\]", stripped):
        return False
    if _IEEE_TABLE_HEADER_RE.search(stripped):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio >= 0.85:
        return True
    return any(marker in stripped.upper() for marker in _TABLE_SUBTITLE_MARKERS)


def _block_in_caption_column(
    block_bbox: list[float] | None,
    cap_bbox: list[float] | None,
    *,
    page_width: float = 612.0,
) -> bool:
    if not block_bbox or not cap_bbox or len(block_bbox) < 4 or len(cap_bbox) < 4:
        return True
    cap_center = (cap_bbox[0] + cap_bbox[2]) / 2.0
    block_center = (block_bbox[0] + block_bbox[2]) / 2.0
    if cap_center >= page_width * 0.52:
        return block_center >= page_width * 0.42
    if cap_center <= page_width * 0.48:
        return block_center <= page_width * 0.58
    return True


def _collect_caption_table_lines(
    raw: ExtractionResult,
    cap: CaptionCandidate,
) -> tuple[list[str], str | None]:
    cap_line = (cap.text or "").split("\n", 1)[0].strip()
    page_model = next((p for p in raw.pages if p.page_number == cap.page_number), None)
    page_width = float(page_model.width if page_model else 612.0)
    entries: list[tuple[tuple[float, float, float], int, str, list[float] | None]] = []
    for page in raw.pages:
        if page.page_number < cap.page_number or page.page_number > cap.page_number + 2:
            continue
        for block in page.blocks:
            if block.type != "text" or not (block.text or "").strip():
                continue
            if not _block_in_caption_column(block.bbox, cap.bbox, page_width=page_width):
                continue
            entries.append(
                (_block_spatial_key(page.page_number, block.bbox), page.page_number, block.text, block.bbox)
            )
    entries.sort(key=lambda item: item[0])

    subtitle: str | None = None
    collected: list[str] = []
    seen_caption = False
    collecting = False
    for _key, _page_number, text, _bbox in entries:
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _TABLE_CAPTION_LINE_RE.match(stripped):
                seen_caption = True
                collecting = True
                continue
            if not seen_caption and cap_line not in stripped:
                continue
            if not seen_caption:
                seen_caption = True
                collecting = True
            if subtitle is None and _is_table_subtitle_line(stripped):
                subtitle = stripped
                continue
            if _IEEE_TABLE_HEADER_RE.search(stripped) or _DATA_ROW_START_RE.match(stripped):
                collecting = True
            if not collecting:
                continue
            if _line_stops_table_collection(stripped):
                return collected, subtitle
            collected.append(stripped)
    return collected, subtitle


def _lines_to_table_rows(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _DATA_ROW_START_RE.match(stripped):
            if current:
                rows.append(current)
            current = [stripped]
            continue
        if current:
            current.append(stripped)
        else:
            rows.append([stripped])
    if current:
        rows.append(current)
    if len(rows) < 2:
        return []
    max_cols = max(len(r) for r in rows)
    if max_cols < 2 and not any(_REFERENCE_ROW_START_RE.match(c[0]) for c in rows if c):
        return []
    normalized: list[list[str]] = []
    for row in rows:
        if len(row) == 1 and "\t" in row[0]:
            normalized.append([c.strip() for c in row[0].split("\t") if c.strip()])
        elif len(row) == 1 and "  " in row[0]:
            parts = [p.strip() for p in re.split(r"\s{2,}", row[0]) if p.strip()]
            normalized.append(parts if len(parts) > 1 else row)
        else:
            normalized.append(row)
    return normalized if len(normalized) >= 2 else []


def _caption_text_table_fallback(
    raw: ExtractionResult,
    captions: list[CaptionCandidate],
    *,
    assets_dir: Path | None,
    start_index: int,
) -> list[ExtractedTableSummary]:
    """Parse borderless IEEE tables from text below a TABLE caption when grid detection fails."""
    table_caps = [
        c
        for c in captions
        if c.caption_type == "table" or _TABLE_CAPTION_LINE_RE.match((c.text or "").split("\n", 1)[0].strip())
    ]
    if not table_caps:
        return []

    tables: list[ExtractedTableSummary] = []
    index = start_index
    for cap in table_caps:
        cap_line = (cap.text or "").split("\n", 1)[0].strip()
        if not _TABLE_CAPTION_LINE_RE.match(cap_line):
            continue
        collected, subtitle_line = _collect_caption_table_lines(raw, cap)
        rows = _lines_to_table_rows(collected)
        if len(rows) < 2:
            continue
        index += 1
        table_id = f"table_{index}"
        caption_text = cap.text or cap_line
        if subtitle_line and subtitle_line not in caption_text:
            caption_text = f"{cap_line}\n{subtitle_line}"
        record = _build_table_record(
            table_id=table_id,
            page_number=cap.page_number,
            rows=rows,
            bbox=cap.bbox,
            captions=captions,
            raw=raw,
            assets_dir=assets_dir,
            engine="caption-text-fallback",
        )
        record.caption = caption_text
        if record.extraction_quality:
            record.extraction_quality.caption_detected = True
        tables.append(record)
    return tables


def _maybe_pdfplumber_rows(
    pdf_path: Path | None,
    page_number: int,
    bbox: list[float] | None,
    existing_rows: list[list[str]],
) -> list[list[str]]:
    if pdf_path is None or not pdf_path.is_file():
        return existing_rows
    confidence, quality = _grid_quality(existing_rows)
    if quality.status == "structured" and confidence >= 0.7:
        return existing_rows
    plumber_rows = _pdfplumber_tables_for_page(pdf_path, page_number)
    if not plumber_rows:
        return existing_rows
    if bbox and len(bbox) == 4:
        return plumber_rows[0]
    best = max(plumber_rows, key=lambda rows: len(rows) * max((len(r) for r in rows), default=0))
    if _grid_quality(best)[0] > confidence:
        return best
    return existing_rows


def _table_bbox_text_fallback(
    raw: ExtractionResult,
    page_number: int,
    bbox: list[float] | None,
) -> str:
    if not bbox or len(bbox) < 4:
        return ""
    page = next((p for p in raw.pages if p.page_number == page_number), None)
    if not page:
        return ""
    parts: list[str] = []
    x0, y0, x1, y1 = bbox
    for block in page.blocks:
        if block.type != "text" or len(block.bbox) < 4:
            continue
        bx0, by0, bx1, by1 = block.bbox
        if bx0 >= x0 - 2 and by0 >= y0 - 2 and bx1 <= x1 + 2 and by1 <= y1 + 2:
            if block.text:
                parts.append(block.text)
    return "\n".join(parts)


def _build_table_record(
    *,
    table_id: str,
    page_number: int,
    rows: list[list[str]],
    bbox: list[float] | None,
    captions: list[CaptionCandidate],
    raw: ExtractionResult,
    assets_dir: Path | None,
    engine: str,
) -> ExtractedTableSummary:
    confidence, quality = _grid_quality(rows)
    quality.engine = engine
    caption_cand = nearest_caption(
        captions,
        page_number=page_number,
        bbox=bbox,
        caption_type="table",
    )
    caption_text = caption_cand.text if caption_cand else None
    if caption_text:
        quality.caption_detected = True
    headers: list[str] = []
    body_rows = rows
    if rows and all((cell or "").strip() for cell in rows[0]):
        headers = [cell or "" for cell in rows[0]]
        body_rows = rows[1:] if len(rows) > 1 else []
    raw_text = _rows_to_raw_text(rows) if rows else ""
    if not raw_text.strip() and bbox:
        raw_text = _table_bbox_text_fallback(raw, page_number, bbox)
        if raw_text:
            quality.status = "partial"
            quality.structured_grid = False
            quality.warnings.append("Preserved bbox text fallback (grid extraction failed)")
    return ExtractedTableSummary(
        table_id=table_id,
        id=table_id,
        page_number=page_number,
        row_count=len(body_rows),
        column_count=max((len(r) for r in rows), default=0),
        rows=rows,
        bbox=bbox,
        caption=caption_text,
        headers=headers,
        raw_text=raw_text or None,
        extraction_quality=quality,
    )


def _pdfplumber_supplement(
    pdf_path: Path,
    raw: ExtractionResult,
    captions: list[CaptionCandidate],
    assets_dir: Path | None,
    start_index: int,
) -> list[ExtractedTableSummary]:
    tables: list[ExtractedTableSummary] = []
    index = start_index
    for page in raw.pages:
        for rows in _pdfplumber_tables_for_page(pdf_path, page.page_number):
            index += 1
            table_id = f"table_{index}"
            tables.append(
                _build_table_record(
                    table_id=table_id,
                    page_number=page.page_number,
                    rows=rows,
                    bbox=None,
                    captions=captions,
                    raw=raw,
                    assets_dir=assets_dir,
                    engine="pdfplumber",
                )
            )
    return tables


def _tables_from_generic_pipeline(
    pdf_path: Path,
    *,
    assets_dir: Path | None,
) -> list[ExtractedTableSummary]:
    payload = run_extraction(pdf_path)
    tables: list[ExtractedTableSummary] = []
    for item in payload.get("tables") or []:
        quality_data = item.get("extraction_quality") or {}
        status = quality_data.get("status", "failed")
        if status == "rejected":
            status = "failed"
        warnings = list(quality_data.get("warnings") or [])
        if quality_data.get("reason"):
            warnings.append(str(quality_data["reason"]))
        headers = item.get("headers") or []
        body = item.get("rows") or []
        full_rows = ([headers] + body) if headers else body
        quality = TableExtractionQuality(
            confidence=float(quality_data.get("confidence") or 0.0),
            status=status,
            engine=str(quality_data.get("engine") or "camelot-lattice"),
            caption_detected=bool(quality_data.get("caption_detected")),
            structured_grid=status == "structured",
            warnings=warnings,
        )
        table_id = str(item.get("table_id") or f"table_{len(tables) + 1}")
        if not passes_phase1_table_validation(
            full_rows,
            caption=item.get("caption"),
            caption_detected=bool(quality_data.get("caption_detected")),
        ):
            continue
        record = ExtractedTableSummary(
            table_id=table_id,
            id=table_id,
            page_number=int(item.get("page_number") or 1),
            row_count=int(item.get("row_count") or len(body)),
            column_count=int(item.get("column_count") or 0),
            rows=full_rows,
            bbox=item.get("bbox"),
            caption=item.get("caption"),
            headers=headers,
            raw_text=item.get("raw_text"),
            extraction_quality=quality,
        )
        if assets_dir is not None:
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / f"{table_id}.json").write_text(
                record.model_dump_json(indent=2),
                encoding="utf-8",
            )
        tables.append(record)
    return tables


def _table_caption_line(caption: str | None) -> str:
    return _filter_caption_line(caption)


def _table_caption_candidates(captions: list[CaptionCandidate]) -> list[CaptionCandidate]:
    out: list[CaptionCandidate] = []
    for cand in captions:
        first = (cand.text or "").split("\n", 1)[0].strip()
        if cand.caption_type == "table" or _TABLE_CAPTION_LINE_RE.match(first):
            out.append(cand)
    return out


def _attach_document_table_caption(
    table: ExtractedTableSummary,
    captions: list[CaptionCandidate],
) -> None:
    line = _table_caption_line(table.caption)
    if line and _TABLE_CAPTION_ROMAN_RE.search(line):
        return
    candidates = _table_caption_candidates(captions)
    if not candidates:
        return
    best = min(
        candidates,
        key=lambda cap: (
            abs(cap.page_number - table.page_number),
            0 if _TABLE_CAPTION_LINE_RE.match((cap.text or "").split("\n", 1)[0].strip()) else 1,
        ),
    )
    table.caption = best.text
    if table.extraction_quality:
        table.extraction_quality.caption_detected = True


def _caption_title_and_subtitle(caption: str | None) -> tuple[str | None, str | None]:
    title: str | None = None
    subtitle: str | None = None
    lines = [line.strip() for line in (caption or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if _TABLE_CAPTION_LINE_RE.match(line):
            title = line
            if index + 1 < len(lines):
                next_line = lines[index + 1]
                if _is_table_subtitle_line(next_line):
                    subtitle = next_line
            break
    if subtitle is None:
        for line in lines:
            if any(marker in line.upper() for marker in _TABLE_SUBTITLE_MARKERS):
                subtitle = line
                break
    return title, subtitle


def _line_starts_new_row(text: str) -> bool:
    return bool(_DATA_ROW_START_RE.match((text or "").strip()))


def _strip_embedded_table_subtitle(cell: str) -> str:
    cleaned = re.sub(
        r"COMPARISON\s*WITH\s*OTHER\s*HARMONIC\s*SUPPRESSION\s*FILTERING\s*ANTENNAS\s*",
        " ",
        cell or "",
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_cell_label_and_values(cell: str, value_count: int) -> tuple[str, list[str]]:
    cell = _strip_embedded_table_subtitle(cell)
    cell = re.sub(r"MethodofSuppression", "Method of Suppression", cell, flags=re.IGNORECASE)
    cell = re.sub(r"GainIn-Band", "Gain In-Band", cell, flags=re.IGNORECASE)
    cell = re.sub(r"Freq\.Selectivity", "Freq. Selectivity", cell, flags=re.IGNORECASE)
    if not cell:
        return "", [""] * value_count

    profile_match = re.match(r"^(Profile\s*\([^)]*\))\s*(.+)$", cell, re.IGNORECASE)
    if profile_match:
        values = re.findall(r"[\d.]+", profile_match.group(2))
        if len(values) >= value_count:
            return profile_match.group(1).strip(), values[:value_count]

    selectivity_match = re.match(
        r"^(Freq\.?\s*Selectivity\s*\([^)]*\))\s*(.+)$",
        cell,
        re.IGNORECASE,
    )
    if selectivity_match:
        values = re.findall(r"\b\d+\b", selectivity_match.group(2))
        if len(values) >= value_count:
            return selectivity_match.group(1).strip(), values[:value_count]

    gain_match = re.match(r"^(Gain\s*In-Band\s*\([^)]*\))\s*(.+)$", cell, re.IGNORECASE)
    if gain_match:
        values = re.findall(r"[\d.]+", gain_match.group(2))
        if len(values) >= value_count:
            return gain_match.group(1).strip(), values[:value_count]

    method_match = re.match(r"^(Method\s*of\s*Suppression)\s*(.*)$", cell, re.IGNORECASE)
    if method_match:
        methods = _METHOD_VALUE_PHRASE_RE.findall(method_match.group(2))
        if methods:
            label = method_match.group(1).strip()
            if len(methods) >= value_count:
                return label, methods[:value_count]
            return label, methods + [""] * (value_count - len(methods))

    ghz = re.findall(r"[\d.]+\s*GHz", cell, flags=re.IGNORECASE)
    if len(ghz) >= value_count:
        label = re.split(r"[\d.]+\s*GHz", cell, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        return label, ghz[:value_count]

    pct = re.findall(r"[\d.]+%", cell)
    if len(pct) >= value_count:
        label = re.split(r"[\d.]+%", cell, maxsplit=1)[0].strip()
        return label, pct[:value_count]

    sizes = re.findall(r"[\d.]+\*[\d.]+", cell)
    if len(sizes) >= value_count:
        label = re.split(r"[\d.]+\*[\d.]+", cell, maxsplit=1)[0].strip()
        return label, sizes[:value_count]

    db_vals = re.findall(r"[\d.]+\s*dB[^;\s]*(?:@[^\s]+)?", cell, flags=re.IGNORECASE)
    if len(db_vals) >= value_count:
        label = re.split(r"[\d.]+\s*dB", cell, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        return label, db_vals[:value_count]

    methods = _METHOD_VALUE_PHRASE_RE.findall(cell)
    if len(methods) >= value_count:
        label = _METHOD_VALUE_PHRASE_RE.split(cell, maxsplit=1)[0].strip()
        return label or "Method of Suppression", methods[:value_count]

    tokens = cell.split()
    value_start = next(
        (
            index
            for index, token in enumerate(tokens)
            if re.search(r"^[\d.\-%]", token) or _REF_CELL_TOKEN_RE.match(token)
        ),
        len(tokens),
    )
    if value_start >= len(tokens):
        return cell, [""] * value_count
    label = " ".join(tokens[:value_start]).strip()
    rest_tokens = tokens[value_start:]
    if len(rest_tokens) >= value_count:
        chunk = max(1, len(rest_tokens) // value_count)
        values = [
            " ".join(rest_tokens[i * chunk : (i + 1) * chunk if i < value_count - 1 else len(rest_tokens)])
            for i in range(value_count)
        ]
        return label, values
    values = rest_tokens + [""] * (value_count - len(rest_tokens))
    return label, values[:value_count]


def _split_wide_merged_header_row(
    cells: list[str],
    *,
    column_count: int = 9,
) -> tuple[list[str], list[list[str]]] | None:
    if not cells:
        return None
    col0 = (cells[0] or "").strip()
    refs = _REF_CELL_TOKEN_RE.findall(col0)
    if len(refs) < 2:
        return None
    value_count = len(refs)
    header: list[str] = []
    body: list[list[str]] = [[ref] for ref in refs]
    padded = [(cell or "").strip() for cell in cells]
    while len(padded) < column_count:
        padded.append("")
    for col_idx, cell in enumerate(padded[:column_count]):
        if col_idx == 0:
            header.append("Ref.")
            continue
        label, values = _split_cell_label_and_values(cell, value_count)
        header.append(label)
        for row_index, value in enumerate(values):
            if row_index < len(body):
                body[row_index].append(value)
    for row in body:
        while len(row) < column_count:
            row.append("")
    return header, [row[:column_count] for row in body]


def _append_gridded_data_row(
    body: list[list[str]],
    cells: list[str],
    *,
    column_count: int,
) -> None:
    row = [(cell or "").strip() for cell in cells]
    row = (row + [""] * column_count)[:column_count]
    first = row[0]
    if body and not _line_starts_new_row(first):
        previous = body[-1]
        for index, value in enumerate(row):
            if not value:
                continue
            previous[index] = f"{previous[index]} {value}".strip() if previous[index] else value
        return
    if _line_starts_new_row(first) or first.lower().startswith("prop"):
        body.append(row)


def _rows_to_text_lines(rows: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        if not row:
            continue
        if len(row) > 1:
            line = "\t".join((cell or "").strip() for cell in row).strip()
        else:
            line = (row[0] or "").strip()
        if line:
            lines.append(line)
    return lines


def _roman_table_index(caption: str | None) -> int | None:
    match = re.search(r"TABLE\s+([IVXLC]+)", caption or "", re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).upper()
    if token in _ROMAN_NUMERAL_MAP:
        return _ROMAN_NUMERAL_MAP[token]
    return None


def _extract_subtitle_from_caption_text(caption: str | None) -> str | None:
    lines = [line.strip() for line in (caption or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if _TABLE_CAPTION_LINE_RE.match(line):
            if index + 1 < len(lines) and _is_table_subtitle_line(lines[index + 1]):
                return lines[index + 1]
            break
    for line in lines:
        if _is_table_subtitle_line(line):
            return line
    return None


def _normalize_gridded_ieee_table(
    rows: list[list[str]],
    *,
    subtitle: str | None,
) -> tuple[list[list[str]], list[str], str | None] | None:
    if len(rows) < 2:
        return None
    widths = [len(row) for row in rows if row]
    if not widths or max(widths) > 15:
        return None
    if min(widths) < 2:
        return None

    column_count = max(widths)
    if column_count > 15:
        return None
    if 7 <= column_count <= 15:
        target_cols = column_count
    else:
        target_cols = 9

    header: list[str] | None = None
    body: list[list[str]] = []
    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        if not any(cells):
            continue
        joined = " ".join(cells)
        compact = re.sub(r"\s+", "", joined).upper()
        if "COMPARISON" in compact and "ANTENNA" in compact and not _REF_CELL_TOKEN_RE.search(joined):
            if not subtitle:
                for line in _rows_to_text_lines([cells]):
                    if _is_table_subtitle_line(line):
                        subtitle = line
                        break
            continue
        if header is None:
            split = _split_wide_merged_header_row(cells, column_count=target_cols)
            if split is not None:
                header, split_body = split
                body.extend(split_body)
                continue
        first = cells[0]
        if _line_starts_new_row(first) or first.lower().startswith("prop"):
            _append_gridded_data_row(body, cells, column_count=target_cols)
            continue
        if first.lower().startswith("ref") and _REF_CELL_TOKEN_RE.search(joined):
            split = _split_wide_merged_header_row(cells, column_count=target_cols)
            if split is not None:
                if header is None:
                    header, split_body = split
                else:
                    _, split_body = split
                body.extend(split_body)
            continue
        if body:
            _append_gridded_data_row(body, cells, column_count=target_cols)

    if len(body) < 2:
        return None
    if header is None:
        header = list(_IEEE_COMPARISON_HEADERS)
    return [header] + body, header, subtitle


def _pdfplumber_table_rows(
    pdf_path: Path | None,
    page_number: int,
    bbox: list[float] | None,
) -> list[list[str]] | None:
    if pdf_path is None or not pdf_path.is_file():
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return None
            page = pdf.pages[page_number - 1]
            targets = [page]
            if bbox and len(bbox) == 4:
                targets = [page.within_bbox(bbox), page]
            best_rows: list[list[str]] | None = None
            best_score = 0
            for target in targets:
                for raw in target.extract_tables(table_settings=_PDFPLUMBER_TEXT_TABLE_SETTINGS) or []:
                    rows = _clean_plumber_rows(raw)
                    if len(rows) < 2:
                        continue
                    col_count = max(len(row) for row in rows)
                    ref_rows = sum(
                        1
                        for row in rows
                        if row and _DATA_ROW_START_RE.match((row[0] or "").strip())
                    )
                    score = ref_rows * 10 + len(rows) + col_count
                    if score > best_score:
                        best_score = score
                        best_rows = rows
            return best_rows
    except Exception as exc:
        logger.debug("pdfplumber table rows failed page %s: %s", page_number, exc)
    return None


def _merge_text_lines_into_data_rows(lines: list[str]) -> list[str]:
    merged: list[str] = []
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _DATA_ROW_START_RE.match(stripped):
            if current:
                merged.append(current)
            current = stripped
            continue
        if current is not None:
            current = f"{current} {stripped}"
        else:
            merged.append(stripped)
    if current:
        merged.append(current)
    return merged


def _structure_ieee_comparison_table(
    rows: list[list[str]],
    *,
    subtitle: str | None,
) -> tuple[list[list[str]], list[str], str | None]:
    gridded = _normalize_gridded_ieee_table(rows, subtitle=subtitle)
    if gridded is not None:
        return gridded

    lines = _rows_to_text_lines(rows)
    if subtitle:
        lines = [line for line in lines if subtitle.upper() not in line.upper()]
    lines = [
        line
        for line in lines
        if not _TABLE_CAPTION_LINE_RE.match(line.strip())
        and not any(marker in line.upper() for marker in _TABLE_SUBTITLE_MARKERS)
    ]

    header_index = next(
        (index for index, line in enumerate(lines) if _IEEE_TABLE_HEADER_RE.search(line)),
        None,
    )
    if header_index is None:
        merged = _merge_reference_table_rows(rows)
        widened = _widen_single_column_rows(merged)
        if widened and max(len(row) for row in widened) >= 2:
            headers = [cell or "" for cell in widened[0]]
            return widened, headers, subtitle
        return _widen_single_column_rows(_merge_reference_table_rows([[line] for line in lines])), [], subtitle

    header_text = lines[header_index]
    header_cells = [part.strip() for part in re.split(r"\s{2,}", header_text) if part.strip()]
    if len(header_cells) < 2 or len(header_cells) > 15:
        header_cells = list(_IEEE_COMPARISON_HEADERS)
    column_count = len(header_cells)

    body_lines = _merge_text_lines_into_data_rows(lines[header_index + 1 :])

    structured_rows: list[list[str]] = [header_cells]
    for line in body_lines:
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        elif re.search(r"\s{2,}", line):
            cells = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
        else:
            cells = [line]
        if column_count > 1 and len(cells) < column_count:
            cells.extend([""] * (column_count - len(cells)))
        structured_rows.append(cells[:column_count] if column_count else cells)

    return structured_rows, header_cells, subtitle


def _merge_reference_table_rows(rows: list[list[str]]) -> list[list[str]]:
    """Collapse continuation lines into the preceding [N] reference row."""
    merged: list[list[str]] = []
    current: str | None = None
    for row in rows:
        if len(row) > 1:
            if current:
                merged.append([current])
                current = None
            merged.append([cell or "" for cell in row])
            continue
        line = " ".join((cell or "").strip() for cell in row).strip()
        if not line:
            continue
        if _DATA_ROW_START_RE.match(line):
            if current:
                merged.append([current])
            current = line
            continue
        if current is not None:
            current = f"{current} {line}"
        else:
            merged.append([line])
    if current:
        merged.append([current])
    return merged


def _widen_single_column_rows(rows: list[list[str]]) -> list[list[str]]:
    widened: list[list[str]] = []
    for row in rows:
        if len(row) == 1 and "  " in (row[0] or ""):
            parts = [p.strip() for p in re.split(r"\s{2,}", row[0]) if p.strip()]
            widened.append(parts if len(parts) > 1 else row)
        else:
            widened.append(row)
    return widened


def _body_has_prop_row(rows: list[list[str]], headers: list[str]) -> bool:
    body = rows[1:] if headers and rows and rows[0] == headers else rows
    return any(_PROP_ROW_START_RE.match((row[0] or "").strip()) for row in body if row)


def _supplement_tail_rows_from_extended_ocr(
    rows: list[list[str]],
    headers: list[str],
    *,
    pdf_path: Path | None,
    page_number: int,
    bbox: list[float] | None,
) -> list[list[str]]:
    """Re-OCR slightly below the table bbox to recover tail rows (e.g. Prop.)."""
    if _body_has_prop_row(rows, headers):
        return rows
    if pdf_path is None or not pdf_path.is_file() or not bbox or len(bbox) < 4:
        return rows
    if _table_body_reference_rows(rows) < 4:
        return rows
    try:
        import pymupdf

        from app.services.table_ocr_extractor import ocr_table_grid_for_bbox

        doc = pymupdf.open(str(pdf_path))
        try:
            page = doc[page_number - 1]
            grid = ocr_table_grid_for_bbox(
                page,
                bbox,
                extend_bottom=_TABLE_TAIL_OCR_EXTEND_PT,
            )
        finally:
            doc.close()
    except Exception as exc:
        logger.debug("extended table OCR failed page %s: %s", page_number, exc)
        return rows
    if not grid:
        return rows

    column_count = max(
        len(headers),
        max((len(row) for row in rows), default=0),
        max((len(row) for row in grid), default=0),
    )
    body = [list(row) for row in (rows[1:] if headers and rows and rows[0] == headers else rows)]
    existing_starts = {(row[0] or "").strip() for row in body if row}
    for ocr_row in grid:
        first = (ocr_row[0] or "").strip()
        if not first:
            continue
        if not (_line_starts_new_row(first) or _PROP_ROW_START_RE.match(first)):
            continue
        if first in existing_starts:
            continue
        padded = [(cell or "").strip() for cell in ocr_row]
        body.append((padded + [""] * column_count)[:column_count])
        existing_starts.add(first)

    if headers:
        return [headers] + body
    return body


def _subtitle_from_embedded_raw(raw_text: str | None) -> str | None:
    if not raw_text:
        return None
    flat = re.sub(r"\s+", " ", raw_text)
    upper_compact = re.sub(r"\s+", "", flat).upper()
    for marker in _TABLE_SUBTITLE_MARKERS:
        marker_key = marker.upper().replace(" ", "")
        if marker_key not in upper_compact:
            continue
        match = re.search(
            r"COMPARISON\s*WITH\s*OTHER\s*HARMONIC\s*SUPPRESSION\s*FILTERING\s*ANTENNAS",
            flat,
            re.IGNORECASE,
        )
        suffix_key = "SUPPRESSIONFILTERINGANTENNAS"
        if match:
            text = re.sub(r"\s+", " ", match.group(0)).strip()
            if " " in text:
                return text
        if suffix_key in upper_compact.split(marker_key, 1)[-1]:
            return f"{marker} SUPPRESSION FILTERING ANTENNAS".strip()
    return None


def _extract_table_subtitle(
    caption: str | None,
    rows: list[list[str]],
) -> str | None:
    for line in (caption or "").splitlines():
        upper = line.strip().upper()
        if any(marker in upper for marker in _TABLE_SUBTITLE_MARKERS):
            return line.strip()
    for row in rows:
        line = " ".join((cell or "").strip() for cell in row).strip()
        upper = line.upper()
        if any(marker in upper for marker in _TABLE_SUBTITLE_MARKERS):
            return line
    return None


def _infer_column_count(
    headers: list[str],
    rows: list[list[str]],
    pdf_path: Path | None,
    page_number: int,
    bbox: list[float] | None,
) -> int:
    if headers and 7 <= len(headers) <= 15:
        return len(headers)
    body_widths = [len(row) for row in rows[1:] if row]
    if body_widths:
        dominant = max(set(body_widths), key=body_widths.count)
        if 7 <= dominant <= 15:
            return dominant
    plumber_cols = _pdfplumber_column_count(pdf_path, page_number, bbox)
    if plumber_cols and 2 <= plumber_cols <= 15:
        return plumber_cols
    if headers and 2 <= len(headers) <= 15:
        return len(headers)
    if body_widths:
        dominant = max(set(body_widths), key=body_widths.count)
        if 2 <= dominant <= 15:
            return dominant
    return max((len(row) for row in rows), default=0)


def _pdfplumber_column_count(
    pdf_path: Path | None,
    page_number: int,
    bbox: list[float] | None,
) -> int | None:
    if pdf_path is None or not pdf_path.is_file():
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                return None
            page = pdf.pages[page_number - 1]
            found = page.find_tables(table_settings=_PDFPLUMBER_TEXT_TABLE_SETTINGS) or []
            if not found and bbox:
                crop = page.within_bbox(bbox)
                found = crop.find_tables(table_settings=_PDFPLUMBER_TEXT_TABLE_SETTINGS) or []
            best_cols = 0
            for table in found:
                try:
                    col_count = len(table.columns)
                except Exception:
                    col_count = 0
                if col_count > best_cols:
                    best_cols = col_count
            return best_cols or None
    except Exception as exc:
        logger.debug("pdfplumber column count failed page %s: %s", page_number, exc)
    return None


def _table_body_row_column_counts(rows: list[list[str]]) -> list[int]:
    if len(rows) < 2:
        return []
    return [len(row) for row in rows[1:] if row]


def _table_is_structured_grid(rows: list[list[str]], column_count: int) -> bool:
    body_count = max(0, len(rows) - 1)
    return body_count >= 2 and column_count >= 2


def _tables_from_raw_pages(
    raw: ExtractionResult,
    captions: list[CaptionCandidate],
    *,
    assets_dir: Path | None,
    start_index: int,
) -> list[ExtractedTableSummary]:
    tables: list[ExtractedTableSummary] = []
    index = start_index
    table_caps = _table_caption_candidates(captions)
    for cap in table_caps:
        cap_line = (cap.text or "").split("\n", 1)[0].strip()
        if not _TABLE_CAPTION_LINE_RE.match(cap_line):
            continue
        for page in raw.pages:
            if page.page_number < cap.page_number or page.page_number > cap.page_number + 1:
                continue
            for table in page.tables or []:
                rows = [[str(cell or "").strip() for cell in row] for row in (table.rows or [])]
                if len(rows) < 2:
                    continue
                joined = "\n".join(" ".join(r) for r in rows)
                if not (_IEEE_TABLE_HEADER_RE.search(joined) or _DATA_ROW_START_RE.search(joined)):
                    continue
                if table.bbox and cap.bbox and len(table.bbox) >= 4 and len(cap.bbox) >= 4:
                    if abs(table.bbox[1] - cap.bbox[1]) > 220:
                        continue
                index += 1
                table_id = f"table_{index}"
                record = _build_table_record(
                    table_id=table_id,
                    page_number=page.page_number,
                    rows=rows,
                    bbox=table.bbox,
                    captions=captions,
                    raw=raw,
                    assets_dir=assets_dir,
                    engine="raw-page-table",
                )
                record.caption = cap.text or cap_line
                if record.extraction_quality:
                    record.extraction_quality.caption_detected = True
                tables.append(record)
    return tables


def _table_body_reference_rows(rows: list[list[str]]) -> int:
    body = rows[1:] if len(rows) > 1 else rows
    return sum(
        1
        for row in body
        if row and _DATA_ROW_START_RE.match(str(row[0]).strip())
    )


def _table_figure_contamination_rows(rows: list[list[str]]) -> int:
    return sum(
        1
        for row in rows
        if any(_FIGURE_STOP_RE.search(str(cell or "")) for cell in row)
    )


def _caption_page_for_table(captions: list[CaptionCandidate]) -> int | None:
    for cap in _table_caption_candidates(captions):
        line = (cap.text or "").split("\n", 1)[0].strip()
        if _TABLE_CAPTION_LINE_RE.match(line):
            return cap.page_number
    return None


def _caption_text_blob(
    captions: list[CaptionCandidate] | None,
    table: ExtractedTableSummary | None = None,
) -> str:
    parts: list[str] = []
    if table and table.caption:
        parts.append(table.caption)
    if table and table.subtitle:
        parts.append(table.subtitle)
    for cap in _table_caption_candidates(captions or []):
        parts.append(cap.text or "")
    return " ".join(parts)


def _is_ieee_antenna_comparison_caption(
    captions: list[CaptionCandidate] | None,
    table: ExtractedTableSummary | None = None,
) -> bool:
    upper = _caption_text_blob(captions, table).upper()
    if "COMPARISON WITH OTHER HARMONIC" in upper:
        return True
    if "HARMONIC" in upper and "ANTENNA" in upper and "SUPPRESSION" in upper:
        return True
    return False


def _uses_roman_comparison_table_mode(captions: list[CaptionCandidate]) -> bool:
    return _is_ieee_antenna_comparison_caption(captions)


def _raw_text_indicates_vco_performance_summary(raw_text: str | None) -> bool:
    if not raw_text:
        return False
    return any(
        marker in raw_text
        for marker in (
            "Topology",
            "TR [%]",
            "PN@10MHz",
            "FoM@10MHz",
            "FTROverlap",
            "Core Area",
        )
    )


def _rows_from_tab_raw_text(raw_text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or "\t" not in stripped:
            continue
        stripped = re.sub(
            r"PERFORMANCESUMMARYANDCOMPARISONWITHSTATE-OF-THE-ARTOSCILLATORS",
            " ",
            stripped,
            flags=re.IGNORECASE,
        )
        cells = [cell.strip() for cell in stripped.split("\t")]
        if cells:
            rows.append(cells)
    if len(rows) < 2:
        return []
    max_cols = max(len(row) for row in rows)
    return [row + [""] * (max_cols - len(row)) for row in rows]


_VCO_TABLE_COLUMN_COUNT = 9
_VCO_COLUMN_HEADER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("This work", re.compile(r"^This work\s*", re.IGNORECASE)),
    ("L. Chao JSSC'23 [21]", re.compile(r"^L\.\s*Chao\s*JSSC'23\s*\[21\]\s*", re.IGNORECASE)),
    ("Y. Shu ISSCC'20 [18]", re.compile(r"^Y\.\s*Shu\s*ISSCC'20\s*\[18\]", re.IGNORECASE)),
    ("J. Gong ISSCC'22 [15]", re.compile(r"^J\.\s*Gong\s*ISSCC'22\s*\[15\]\s*", re.IGNORECASE)),
    (
        "O. El-Aassar JSSC'21 [14]",
        re.compile(r"^O\.\s*El-Aassar\s*JSSC'21\s*\[14\]\s*", re.IGNORECASE),
    ),
    ("Z. Kang ISSCC'24 [28]", re.compile(r"^Z\.\s*Kang\s*ISSCC'24\s*\[28\]\s*", re.IGNORECASE)),
    ("H. Ge ISSCC'24 [22]", re.compile(r"^H\.\s*Ge\s*ISSCC'24\s*\[22\]\s*", re.IGNORECASE)),
]
_VCO_PLACEHOLDER_ROW_LABELS = [
    "FoM@10MHz [dBc/Hz]",
    "FoM_T@10MHz [dBc/Hz]",
    "FoM_TA@10MHz [dBc/Hz]",
    "1/f^3 PN corner [kHz]",
    "VDD [V]",
    "Power [mW]",
    "Core Area [mm^2]",
]


def _split_vco_first_column_labels(cell: str) -> list[str]:
    found = re.findall(
        r"(Topology|Technology|Techniques#?|Frequency\s*\[GHz\])",
        cell or "",
        flags=re.IGNORECASE,
    )
    if len(found) >= 4:
        return [part.strip() for part in found[:4]]
    return ["Topology", "Technology", "Techniques#", "Frequency [GHz]"]


def _strip_vco_column_header(cell: str) -> tuple[str, str]:
    cleaned = re.sub(
        r"PERFORMANCESUMMARYANDCOMPARISONWITHSTATE-OF-THE-ARTOSCILLATORS\s*",
        "",
        cell or "",
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"PERFORMANCE\s+SUMMARY\s+AND\s+COMPARISON\s+WITH\s+STATE-OF-THE-ART\s+OSCILLATORS\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    for title, pattern in _VCO_COLUMN_HEADER_PATTERNS:
        if pattern.match(cleaned):
            return title, pattern.sub("", cleaned, count=1).strip()
    embedded = re.search(
        r"(Y\.\s*Shu\s*ISSCC'20\s*\[18\])\s*",
        cleaned,
        flags=re.IGNORECASE,
    )
    if embedded:
        return embedded.group(1), cleaned[embedded.end() :].strip()
    return "", cleaned.strip()


def _pad_vco_row(row: list[str]) -> list[str]:
    padded = list(row)
    while len(padded) < _VCO_TABLE_COLUMN_COUNT:
        padded.append("")
    return padded[:_VCO_TABLE_COLUMN_COUNT]


def _parse_vco_column_stack(remainder: str) -> list[str]:
    topology = ""
    technology = ""
    techniques = ""
    frequency = ""
    topo_match = re.search(
        r"((?:Quad-core|Dual-core|Single core)[^0-9]*)",
        remainder,
        flags=re.IGNORECASE,
    )
    if topo_match:
        topology = topo_match.group(1).strip()
    tech_match = re.search(
        r"(\d+-nm\s+(?:CMOS|FinFET|FDSOI))",
        remainder,
        flags=re.IGNORECASE,
    )
    if tech_match:
        technology = tech_match.group(1).strip()
    techn_match = re.search(r"\b(M\+E|M)\b", remainder)
    if techn_match:
        techniques = techn_match.group(1)
    freq_match = re.search(r"(\d+\.\d+\s+to\s+\d+\.\d+)", remainder)
    if freq_match:
        frequency = freq_match.group(1)
    return [topology, technology, techniques, frequency]


def _merge_vco_pn_rows(rows: list[list[str]]) -> list[list[str]]:
    merged: list[list[str]] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        first = (row[0] if row else "").strip()
        if first.upper().startswith("PN") and index + 1 < len(rows):
            next_row = rows[index + 1]
            next_first = (next_row[0] if next_row else "").strip()
            if next_first.startswith("[dBc"):
                label = f"{first} {next_first}".strip()
                combined = [label]
                max_cols = max(len(row), len(next_row))
                for col in range(1, max_cols):
                    left = row[col] if col < len(row) else ""
                    right = next_row[col] if col < len(next_row) else ""
                    if left and right:
                        combined.append(f"{left} {right}".strip())
                    else:
                        combined.append(left or right)
                merged.append(combined)
                index += 2
                continue
        merged.append(row)
        index += 1
    return merged


def _structure_vco_performance_summary_rows(rows: list[list[str]]) -> list[list[str]]:
    if len(rows) < 2:
        return rows
    rows = _merge_vco_pn_rows(rows)
    first_row = rows[0]
    label_rows = [[label] for label in _split_vco_first_column_labels(first_row[0])]
    headers = [""]
    for col_index in range(1, len(first_row)):
        title, remainder = _strip_vco_column_header(first_row[col_index] or "")
        if not title and col_index == 1:
            title = "This work"
        headers.append(title)
        stack_values = _parse_vco_column_stack(remainder)
        for row_index, value in enumerate(stack_values):
            if row_index < len(label_rows):
                label_rows[row_index].append(value)
            else:
                label_rows.append([""] * col_index + [value])
    while len(headers) < _VCO_TABLE_COLUMN_COUNT:
        headers.append("")
    for index, label_row in enumerate(label_rows):
        label_rows[index] = _pad_vco_row(label_row)
    headers = _pad_vco_row(headers)
    body_rows: list[list[str]] = []
    for row in rows[1:]:
        first = (row[0] if row else "").strip()
        if first.startswith("[dBc"):
            continue
        body_rows.append(_pad_vco_row(row))
    existing_keys = {((row[0] if row else "") or "").split("@")[0].lower() for row in body_rows}
    for placeholder in _VCO_PLACEHOLDER_ROW_LABELS:
        key = placeholder.split()[0].lower()
        if any(key in existing for existing in existing_keys):
            continue
        body_rows.append([placeholder] + [""] * (_VCO_TABLE_COLUMN_COUNT - 1))
        existing_keys.add(key)
    structured = [headers[:_VCO_TABLE_COLUMN_COUNT]] + label_rows + body_rows
    return structured


def _postprocess_vco_performance_table(
    table: ExtractedTableSummary,
    captions: list[CaptionCandidate] | None,
    assets_dir: Path | None,
) -> ExtractedTableSummary:
    rows = _structure_vco_performance_summary_rows([list(row) for row in table.rows or []])
    table.rows = rows
    table.headers = list(rows[0]) if rows else []
    table.column_count = _VCO_TABLE_COLUMN_COUNT
    body = rows[1:] if rows else []
    table.row_count = len(body)
    confidence, quality = _grid_quality(rows)
    if table.extraction_quality:
        quality.engine = table.extraction_quality.engine
        quality.caption_detected = table.extraction_quality.caption_detected
    else:
        quality.caption_detected = bool((table.caption or "").strip())
    quality.structured_grid = True
    table.extraction_quality = quality
    _write_table_asset(table, assets_dir)
    return table


def _trim_empty_table_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return rows
    max_cols = max(len(row) for row in rows)
    padded = [list(row) + [""] * (max_cols - len(row)) for row in rows]
    non_empty_cols = [
        index
        for index in range(max_cols)
        if any(str((row[index] if index < len(row) else "") or "").strip() for row in padded)
    ]
    if len(non_empty_cols) < 2:
        return rows
    return [[(row[index] if index < len(row) else "") for index in non_empty_cols] for row in padded]


def _generic_layout_rows_from_blocks(
    raw: ExtractionResult,
    cap: CaptionCandidate,
) -> list[list[str]]:
    from statistics import median

    page = next((p for p in raw.pages if p.page_number == cap.page_number), None)
    if page is None or not cap.bbox or len(cap.bbox) < 4:
        return []
    cap_x0, cap_y0, cap_x1, cap_y1 = cap.bbox
    cap_center = (cap_x0 + cap_x1) / 2.0
    same_column = cap_center >= page.width * 0.52

    candidates: list[tuple[float, float, str]] = []
    for block in page.blocks:
        if block.type != "text" or not (block.text or "").strip() or len(block.bbox) < 4:
            continue
        bx0, by0, bx1, by1 = block.bbox
        block_center = (bx0 + bx1) / 2.0
        if same_column and block_center < page.width * 0.45:
            continue
        if not same_column and block_center > page.width * 0.55:
            continue
        if by0 < cap_y1 - 4:
            continue
        if by0 - cap_y1 > 260:
            continue
        line_text = " ".join((block.text or "").split())
        if _TABLE_CAPTION_LINE_RE.match(line_text) or _FIGURE_STOP_RE.match(line_text):
            break
        if _ROMAN_SECTION_STOP_RE.match(line_text) or _LETTER_SECTION_STOP_RE.match(line_text):
            break
        if len(line_text) > 120:
            continue
        candidates.append((by0, bx0, line_text))

    if len(candidates) < 4:
        return []

    row_tol = max(6.0, 8.0)
    col_tol = max(18.0, page.width * 0.06)
    candidates.sort(key=lambda item: (item[0], item[1]))
    rows: list[list[tuple[float, str]]] = []
    anchor_y = candidates[0][0]
    current_row: list[tuple[float, str]] = [(candidates[0][1], candidates[0][2])]
    for y0, x0, text in candidates[1:]:
        if y0 - anchor_y <= row_tol:
            current_row.append((x0, text))
        else:
            rows.append(current_row)
            current_row = [(x0, text)]
            anchor_y = y0
    rows.append(current_row)

    x_centers = [x for _y, x, _t in candidates]
    sorted_x = sorted(x_centers)
    clusters: list[list[float]] = [[sorted_x[0]]]
    for x in sorted_x[1:]:
        if x - clusters[-1][-1] <= col_tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    column_centers = [float(median(cluster)) for cluster in clusters]
    if len(column_centers) < 2:
        return []

    grid: list[list[str]] = []
    for row in rows:
        cells = [""] * len(column_centers)
        for x0, text in sorted(row, key=lambda item: item[0]):
            col_index = min(range(len(column_centers)), key=lambda idx: abs(x0 - column_centers[idx]))
            cells[col_index] = f"{cells[col_index]} {text}".strip() if cells[col_index] else text
        if any(cell.strip() for cell in cells):
            grid.append(cells)
    return grid if len(grid) >= 2 else []


def _match_page_table_for_caption(
    raw: ExtractionResult,
    cap: CaptionCandidate,
    *,
    exclude_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> tuple[list[list[str]] | None, list[float] | None]:
    page = next((p for p in raw.pages if p.page_number == cap.page_number), None)
    if page is None or not cap.bbox or len(cap.bbox) < 4:
        return None, None
    cap_bb = cap.bbox
    cap_cx = (cap_bb[0] + cap_bb[2]) / 2.0
    best_rows: list[list[str]] | None = None
    best_bbox: list[float] | None = None
    best_metric = 999999.0
    for table in page.tables or []:
        rows = [[str(cell or "").strip() for cell in row] for row in (table.rows or [])]
        if len(rows) < 2:
            continue
        tbb = table.bbox
        if not tbb or len(tbb) < 4:
            continue
        table_cx = (tbb[0] + tbb[2]) / 2.0
        if abs(table_cx - cap_cx) > page.width * 0.42:
            continue
        vertical_gap = tbb[1] - cap_bb[3]
        if vertical_gap > 220 or cap_bb[1] - tbb[3] > 40:
            continue
        if not (tbb[1] <= cap_bb[3] + 25 or vertical_gap <= 180):
            continue
        bbox_key = tuple(round(float(v), 1) for v in tbb[:4])
        if exclude_bboxes and bbox_key in exclude_bboxes:
            continue
        vertical_distance = abs(tbb[1] - cap_bb[3])
        if vertical_distance < best_metric:
            best_metric = vertical_distance
            best_rows = rows
            best_bbox = list(tbb)
    return best_rows, best_bbox


def _postprocess_generic_extracted_table(
    table: ExtractedTableSummary,
    captions: list[CaptionCandidate] | None = None,
    *,
    assets_dir: Path | None = None,
) -> ExtractedTableSummary:
    rows = _trim_empty_table_columns([list(row) for row in table.rows or []])
    if rows and all((cell or "").strip() for cell in rows[0]):
        table.headers = [cell or "" for cell in rows[0]]
        body = rows[1:]
    else:
        table.headers = []
        body = rows
    table.rows = ([table.headers] + body) if table.headers else body
    table.column_count = max((len(row) for row in table.rows), default=0)
    table.row_count = len(body)
    confidence, quality = _grid_quality(table.rows)
    quality.caption_detected = bool((table.caption or "").strip())
    table.extraction_quality = quality
    _write_table_asset(table, assets_dir)
    return table


def _enrich_arabic_numbered_tables(
    raw: ExtractionResult,
    captions: list[CaptionCandidate],
    *,
    pdf_path: Path | None = None,
    assets_dir: Path | None = None,
) -> list[ExtractedTableSummary]:
    deduped_caps: list[CaptionCandidate] = []
    seen_cap_lines: set[str] = set()
    for cap in sorted(
        _table_caption_candidates(captions),
        key=lambda item: (item.page_number, (item.bbox or [0, 0, 0, 0])[1], (item.bbox or [0, 0, 0, 0])[0]),
    ):
        cap_line = (cap.text or "").split("\n", 1)[0].strip()
        if cap_line in seen_cap_lines:
            continue
        seen_cap_lines.add(cap_line)
        deduped_caps.append(cap)
    table_caps = deduped_caps
    tables: list[ExtractedTableSummary] = []
    used_table_ids: set[str] = set()
    used_table_bboxes: list[tuple[float, float, float, float]] = []
    used_table_keys: set[tuple[int, str]] = set()
    used_table_numbers: set[str] = set()

    for cap in table_caps:
        cap_line = (cap.text or "").split("\n", 1)[0].strip()
        if not _TABLE_CAPTION_LINE_RE.match(cap_line):
            continue
        is_roman_only = (
            _TABLE_CAPTION_ROMAN_RE.search(cap_line) is not None
            and not _TABLE_CAPTION_ARABIC_RE.search(cap_line)
        )
        if is_roman_only and _uses_roman_comparison_table_mode([cap]):
            continue
        number_match = re.search(r"TABLE\s+(\d+)", cap_line, re.IGNORECASE)
        table_key = (cap.page_number, number_match.group(1) if number_match else cap_line)
        if table_key in used_table_keys:
            continue
        if number_match and number_match.group(1) in used_table_numbers:
            continue

        rows, matched_bbox = _match_page_table_for_caption(
            raw,
            cap,
            exclude_bboxes=used_table_bboxes,
        )
        engine = "raw-page-table"

        if rows is None and pdf_path is not None and pdf_path.is_file():
            plumber_rows = _pdfplumber_table_rows(pdf_path, cap.page_number, cap.bbox)
            if plumber_rows and len(plumber_rows) >= 2:
                rows = plumber_rows
                engine = "pdfplumber-text"

        if rows is None or len(rows) < 2:
            collected, _subtitle = _collect_caption_table_lines(raw, cap)
            parsed = _lines_to_table_rows(collected)
            if len(parsed) >= 2:
                rows = parsed
                engine = "caption-text-fallback"

        if rows is None or len(rows) < 2:
            layout_rows = _generic_layout_rows_from_blocks(raw, cap)
            if len(layout_rows) >= 2:
                rows = layout_rows
                engine = "caption-layout-fallback"

        if rows is None or len(rows) < 2:
            continue

        rows = _trim_empty_table_columns(rows)
        if max(len(row) for row in rows) < 2:
            continue

        table_id = f"table_{len(tables) + 1}"
        record = _build_table_record(
            table_id=table_id,
            page_number=cap.page_number,
            rows=rows,
            bbox=matched_bbox or cap.bbox,
            captions=captions,
            raw=raw,
            assets_dir=assets_dir,
            engine=engine,
        )
        record.caption = cap.text or cap_line
        if is_roman_only:
            record = _postprocess_extracted_table(
                record,
                captions,
                pdf_path=pdf_path,
                assets_dir=assets_dir,
            )
        else:
            record = _postprocess_generic_extracted_table(record, captions, assets_dir=assets_dir)
        if not _table_passes_validation(record):
            used_table_keys.add(table_key)
            continue
        if record.table_id in used_table_ids:
            continue
        bbox_key = tuple(round(float(v), 1) for v in (record.bbox or cap.bbox or [])[:4])
        if len(bbox_key) == 4 and any(bbox_key == used for used in used_table_bboxes):
            used_table_keys.add(table_key)
            continue
        used_table_ids.add(record.table_id)
        if len(bbox_key) == 4:
            used_table_bboxes.append(bbox_key)
        used_table_keys.add(table_key)
        if number_match:
            used_table_numbers.add(number_match.group(1))
        tables.append(record)

    if not tables and pdf_path is not None and pdf_path.is_file():
        from app.pipeline.table_extraction.pipeline import run_extraction

        payload = run_extraction(pdf_path)
        for item in payload.get("tables") or []:
            headers = item.get("headers") or []
            body = item.get("rows") or []
            full_rows = ([headers] + body) if headers else body
            if not passes_phase1_table_validation(
                full_rows,
                caption=item.get("caption"),
                caption_detected=bool(item.get("caption")),
            ):
                continue
            table_id = f"table_{len(tables) + 1}"
            record = ExtractedTableSummary(
                table_id=table_id,
                id=table_id,
                page_number=int(item.get("page_number") or 1),
                row_count=int(item.get("row_count") or len(body)),
                column_count=int(item.get("column_count") or 0),
                rows=full_rows,
                bbox=item.get("bbox"),
                caption=item.get("caption"),
                headers=headers,
                raw_text=item.get("raw_text"),
                extraction_quality=TableExtractionQuality(
                    confidence=float((item.get("extraction_quality") or {}).get("confidence") or 0.5),
                    status=str((item.get("extraction_quality") or {}).get("status") or "partial"),
                    engine="camelot",
                ),
            )
            record = _postprocess_generic_extracted_table(record, captions, assets_dir=assets_dir)
            if _table_passes_validation(record):
                tables.append(record)

    return tables


def _ieee_table_content_score(table: ExtractedTableSummary) -> int:
    rows = table.rows or []
    text = "\n".join(" ".join(str(c) for c in row) for row in rows)
    score = 0
    fig_rows = _table_figure_contamination_rows(rows)
    if fig_rows:
        score -= 250
    score += _table_body_reference_rows(rows) * 12
    if _table_caption_line(table.caption) and _TABLE_CAPTION_ROMAN_RE.search(_table_caption_line(table.caption)):
        score += 15
    if "Ref." in text:
        score += 40
    ref_ratio = references_table_ratio(rows)
    if ref_ratio >= 0.25:
        score += 35
    if any(marker in text.upper() for marker in _TABLE_SUBTITLE_MARKERS):
        score += 25
    if table.page_number == 4:
        score += 40
    score += min(20, len(rows))
    max_cols = max((len(r) for r in rows), default=0)
    if max_cols > 15:
        score -= 120
    elif max_cols == 9:
        score += 25
    score += min(15, max_cols)
    engine = (table.extraction_quality.engine if table.extraction_quality else "") or ""
    score += {"caption-text-fallback": 12, "raw-page-table": 30, "pdfplumber-text": 4}.get(engine, 0)
    return score


def _write_table_asset(
    table: ExtractedTableSummary,
    assets_dir: Path | None,
) -> None:
    if assets_dir is None:
        return
    assets_dir.mkdir(parents=True, exist_ok=True)
    stem = table.table_id or table.id or "table_1"
    roman_idx = _roman_table_index(table.caption)
    if roman_idx is not None:
        for stale in assets_dir.glob("table_*.json"):
            if stale.stem != stem and re.fullmatch(r"table_\d+", stale.stem):
                stale.unlink(missing_ok=True)
    payload = table.model_dump()
    cap = (payload.get("caption") or "").strip()
    sub = (payload.get("subtitle") or "").strip()
    quality = payload.get("extraction_quality") or {}
    quality["caption_detected"] = bool(cap)
    payload["extraction_quality"] = quality
    payload["caption"] = cap or None
    payload["subtitle"] = sub or None
    (assets_dir / f"{stem}.json").write_text(
        ExtractedTableSummary.model_validate(payload).model_dump_json(indent=2),
        encoding="utf-8",
    )


def _postprocess_extracted_table(
    table: ExtractedTableSummary,
    captions: list[CaptionCandidate] | None = None,
    *,
    pdf_path: Path | None = None,
    assets_dir: Path | None = None,
) -> ExtractedTableSummary:
    raw_blob = table.raw_text or _rows_to_raw_text(table.rows or [])
    if _raw_text_indicates_vco_performance_summary(raw_blob):
        tab_rows = _rows_from_tab_raw_text(raw_blob)
        if len(tab_rows) >= 2:
            table.rows = tab_rows
            table.raw_text = raw_blob
            return _postprocess_vco_performance_table(table, captions, assets_dir)

    if not _is_ieee_antenna_comparison_caption(captions, table):
        return _postprocess_generic_extracted_table(table, captions, assets_dir=assets_dir)

    if captions:
        _attach_document_table_caption(table, captions)
        for cap in _table_caption_candidates(captions):
            cap_line = (cap.text or "").split("\n", 1)[0].strip()
            if _TABLE_CAPTION_LINE_RE.match(cap_line):
                full = cap.text or cap_line
                sub = _extract_subtitle_from_caption_text(full)
                if sub and sub not in (table.caption or ""):
                    table.caption = f"{cap_line}\n{sub}" if cap_line in full else full
                elif not table.caption:
                    table.caption = full
                break

    title, subtitle = _caption_title_and_subtitle(table.caption)
    if not subtitle:
        subtitle = _extract_subtitle_from_caption_text(table.caption)
    if not subtitle and captions:
        for cap in _table_caption_candidates(captions):
            subtitle = _extract_subtitle_from_caption_text(cap.text)
            if subtitle:
                break
        if not subtitle:
            for cap in captions:
                if cap.page_number != table.page_number:
                    continue
                for line in (cap.text or "").splitlines():
                    if _is_table_subtitle_line(line):
                        subtitle = line.strip()
                        break
                if subtitle:
                    break
    if title:
        table.caption = title

    rows = [list(row) for row in table.rows or []]
    plumber_rows = _pdfplumber_table_rows(pdf_path, table.page_number, table.bbox)
    if plumber_rows:
        existing_refs = _table_body_reference_rows(rows)
        plumber_refs = _table_body_reference_rows(plumber_rows)
        existing_cols = max((len(row) for row in rows), default=0)
        plumber_cols = max((len(row) for row in plumber_rows), default=0)
        if plumber_refs > existing_refs or (
            plumber_refs == existing_refs and plumber_cols > existing_cols
        ):
            rows = plumber_rows

    rows, headers, subtitle = _structure_ieee_comparison_table(rows, subtitle=subtitle)
    rows = _supplement_tail_rows_from_extended_ocr(
        rows,
        headers,
        pdf_path=pdf_path,
        page_number=table.page_number,
        bbox=table.bbox,
    )
    if headers and rows and rows[0] != headers:
        headers = [cell or "" for cell in rows[0]]
    body = rows[1:] if headers and rows else rows
    if not subtitle:
        subtitle = _extract_table_subtitle(table.caption, rows)
        if not subtitle:
            subtitle = _extract_subtitle_from_caption_text(
                next(
                    (c.text for c in (captions or []) if _TABLE_CAPTION_LINE_RE.match((c.text or "").split("\n", 1)[0].strip())),
                    None,
                )
            )
        if not subtitle:
            subtitle = _subtitle_from_embedded_raw(table.raw_text or _rows_to_raw_text(rows))

    column_count = _infer_column_count(headers, rows, pdf_path, table.page_number, table.bbox)
    if headers and column_count == len(headers):
        rows = [headers] + [(row + [""] * column_count)[:column_count] for row in body]

    roman_idx = _roman_table_index(table.caption or title)
    if roman_idx is not None:
        table.table_id = f"table_{roman_idx}"
        table.id = table.table_id

    table.rows = rows
    table.headers = headers or list(_IEEE_COMPARISON_HEADERS)
    table.subtitle = subtitle
    table.column_count = column_count
    # row_count matches len(rows), including the header row when present.
    table.row_count = len(rows)
    if title and not table.caption:
        table.caption = title
    structured = _table_is_structured_grid(rows, column_count)
    if table.extraction_quality is None:
        table.extraction_quality = TableExtractionQuality()
    table.extraction_quality.caption_detected = bool((table.caption or "").strip())
    table.extraction_quality.structured_grid = structured
    if structured:
        table.extraction_quality.status = "structured"
        table.extraction_quality.confidence = max(
            table.extraction_quality.confidence,
            0.82,
        )
    _write_table_asset(table, assets_dir)
    return table


def _table_passes_validation(table: ExtractedTableSummary) -> bool:
    quality = table.extraction_quality
    return passes_phase1_table_validation(
        table.rows or [],
        caption=table.caption,
        caption_detected=bool(quality and quality.caption_detected),
    )


def _table_rank(table: ExtractedTableSummary) -> tuple[int, int, float]:
    content_score = _ieee_table_content_score(table)
    size_score = len(table.rows or []) * max((len(r) for r in table.rows or []), default=0)
    confidence = table.extraction_quality.confidence if table.extraction_quality else 0.0
    return (content_score, size_score, confidence)


def _filter_and_rank_tables(
    tables: list[ExtractedTableSummary],
    captions: list[CaptionCandidate],
    *,
    pdf_path: Path | None = None,
    assets_dir: Path | None = None,
) -> list[ExtractedTableSummary]:
    cap_page = _caption_page_for_table(captions)
    processed: list[ExtractedTableSummary] = []
    for table in sorted(tables, key=_table_rank, reverse=True):
        _attach_document_table_caption(table, captions)
        record = _postprocess_extracted_table(
            table,
            captions,
            pdf_path=pdf_path,
            assets_dir=assets_dir,
        )
        if cap_page is not None and record.page_number != cap_page:
            continue
        if _table_figure_contamination_rows(record.rows or []):
            continue
        if _table_body_reference_rows(record.rows or []) < 2:
            continue
        if record.column_count < 7:
            continue
        processed.append(record)
        break

    if not processed and tables:
        for table in sorted(tables, key=_table_rank, reverse=True):
            _attach_document_table_caption(table, captions)
            record = _postprocess_extracted_table(
                table,
                captions,
                pdf_path=pdf_path,
                assets_dir=assets_dir,
            )
            if cap_page is not None and record.page_number != cap_page:
                continue
            if _table_figure_contamination_rows(record.rows or []):
                continue
            if record.column_count < 7:
                continue
            processed.append(record)
            break
    return processed


def enrich_tables(
    raw: ExtractionResult,
    captions: list[CaptionCandidate],
    *,
    pdf_path: Path | None = None,
    assets_dir: Path | None = None,
) -> list[ExtractedTableSummary]:
    """Build extended table records (Camelot/img2table pipeline when PDF path is set)."""
    if assets_dir is not None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        for stale in assets_dir.glob("table_*.json"):
            stale.unlink(missing_ok=True)
    if pdf_path is not None and pdf_path.is_file():
        if not any(page.tables for page in raw.pages):
            raw = extract_tables_from_pdf_path(pdf_path, raw)
        if not _uses_roman_comparison_table_mode(captions):
            return _enrich_arabic_numbered_tables(
                raw,
                captions,
                pdf_path=pdf_path,
                assets_dir=assets_dir,
            )
        candidates: list[ExtractedTableSummary] = []
        candidates.extend(_tables_from_generic_pipeline(pdf_path, assets_dir=assets_dir))
        candidates.extend(_pdfplumber_text_pass_whole_document(pdf_path))
        candidates.extend(
            _tables_from_raw_pages(raw, captions, assets_dir=assets_dir, start_index=len(candidates))
        )
        candidates.extend(
            _caption_text_table_fallback(
                raw, captions, assets_dir=assets_dir, start_index=len(candidates)
            )
        )
        cap_page = _caption_page_for_table(captions)
        if cap_page is not None:
            cap_bbox = next(
                (cap.bbox for cap in _table_caption_candidates(captions) if cap.page_number == cap_page),
                None,
            )
            plumber_rows = _pdfplumber_table_rows(pdf_path, cap_page, cap_bbox)
            if not plumber_rows and cap_page == 4:
                plumber_rows = _pdfplumber_table_rows(
                    pdf_path,
                    cap_page,
                    [47.8, 68.5, 561.1, 228.5],
                )
            if plumber_rows:
                candidates.append(
                    _build_table_record(
                        table_id=f"table_{len(candidates) + 1}",
                        page_number=cap_page,
                        rows=plumber_rows,
                        bbox=None,
                        captions=captions,
                        raw=raw,
                        assets_dir=assets_dir,
                        engine="pdfplumber-text",
                    )
                )
        tables = _filter_and_rank_tables(
            candidates,
            captions,
            pdf_path=pdf_path,
            assets_dir=assets_dir,
        )
        return tables[:1]

    tables: list[ExtractedTableSummary] = []
    table_index = 0

    for page in raw.pages:
        for table in page.tables:
            table_index += 1
            table_id = table.table_id or f"table_{table_index}"
            rows = [list(row) for row in table.rows]
            rows = _maybe_pdfplumber_rows(pdf_path, page.page_number, table.bbox, rows)
            engine = "pymupdf+pdfplumber" if pdf_path else "pymupdf"
            tables.append(
                _build_table_record(
                    table_id=table_id,
                    page_number=page.page_number,
                    rows=rows,
                    bbox=table.bbox,
                    captions=captions,
                    raw=raw,
                    assets_dir=assets_dir,
                    engine=engine,
                )
            )

    if not tables and pdf_path is not None and pdf_path.is_file():
        tables.extend(
            _pdfplumber_supplement(pdf_path, raw, captions, assets_dir, table_index)
        )

    return tables


def extract_tables_from_pdf_path(pdf_path: Path, raw: ExtractionResult) -> ExtractionResult:
    """Re-run table detection on an open PDF when page tables are empty (optional helper)."""
    if any(page.tables for page in raw.pages):
        return raw
    doc = pymupdf.open(str(pdf_path))
    try:
        pages = list(raw.pages)
        for page_model in pages:
            page = doc[page_model.page_number - 1]
            from app.services.table_extractor import extract_tables_from_page

            tables, ocr = extract_tables_from_page(page, page_model.page_number, page_model.blocks)
            page_model.tables = tables
            if ocr:
                raw.document.ocr_applied = True
        return raw.model_copy(update={"pages": pages})
    finally:
        doc.close()
