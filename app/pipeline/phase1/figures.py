"""Figure / image object extraction for Phase 1 (caption-driven, multi-signal)."""



from __future__ import annotations



import logging
import re
import unicodedata
from pathlib import Path



import pymupdf



from app.models.extracted_document import (
    ExtractedFigure,
    ExtractedSubfigure,
    FigureExtractionQuality,
    FigureKind,
)

from app.models.extraction import ExtractionResult

from app.pipeline.phase1.captions import CaptionCandidate

from app.pipeline.phase1.caption_parse import parse_figure_number, subfigure_labels
from app.pipeline.phase1.figure_detection import (
    MatchedFigure,
    _iou,
    _union_bbox,
    _whitespace_regions_above_caption,
    collect_figure_regions,
    figure_caption_candidates,
    match_caption_to_region,
    render_region_png,
    zone_render_candidate,
)
from app.pipeline.phase1.caption_parse import (
    _MAX_FIGURE_CAPTION_LINES,
    figure_caption_boundary_line,
    figure_caption_continuation_line,
    find_subfigure_pair_line_near_caption,
    parse_figure_number,
)
from app.pipeline.phase1.subfigure_group import resolve_subfigure_group

_SUBFIGURE_LABEL_RE = re.compile(r"\(([a-z])\)", re.IGNORECASE)
_FIGURE_CAPTION_START_RE = re.compile(r"^fig(?:ure)?\.?\s*\d+", re.IGNORECASE)
_SECTION_HEADING_STOP_RE = re.compile(
    r"^(?:[IVXLC]+\.\s+[A-Z]|[A-H]\.\s+[A-Za-z])",
    re.IGNORECASE,
)
_SUBFIGURE_Y_BAND = 400.0
_MIN_SUBFIGURE_AREA = 2_500.0



logger = logging.getLogger(__name__)



MAX_LOGO_AREA = 12_000.0

TOP_BAND_RATIO = 0.14

BOTTOM_BAND_RATIO = 0.88





def _area(bbox: list[float]) -> float:

    if len(bbox) < 4:

        return 0.0

    return max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))





def _classify_unmatched(

    page_number: int,

    page_height: float,

    bbox: list[float],

    page_count: int,

) -> FigureKind:

    area = _area(bbox)

    if area < 800:

        return "decorative"

    y_mid = (bbox[1] + bbox[3]) / 2.0

    if page_number == 1 and y_mid < page_height * TOP_BAND_RATIO and area < MAX_LOGO_AREA:

        return "logo"

    if page_number >= max(1, page_count - 1) and y_mid > page_height * BOTTOM_BAND_RATIO and area < 25_000:

        return "author_photo"

    return "uncertain"





def _save_pixmap(doc: pymupdf.Document, xref: int, path: Path) -> bool:

    try:

        pix = pymupdf.Pixmap(doc, xref)

        if pix.n - pix.alpha >= 4:

            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

        path.parent.mkdir(parents=True, exist_ok=True)

        pix.save(str(path))

        return True

    except Exception as exc:

        logger.debug("Figure pixmap save failed xref=%s: %s", xref, exc)

        return False





def _text_block_bboxes(raw: ExtractionResult, page_number: int) -> list[list[float]]:

    bboxes: list[list[float]] = []

    for page in raw.pages:

        if page.page_number != page_number:

            continue

        for block in page.blocks:

            if block.type == "text" and len(block.bbox) >= 4:

                bboxes.append(list(block.bbox))

    return bboxes





def _parse_figure_number(text: str) -> int | None:
    return parse_figure_number(text)


def _horizontal_overlap_ratio(a: list[float], b: list[float]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    left = max(a[0], b[0])
    right = min(a[2], b[2])
    overlap = max(0.0, right - left)
    width_a = max(1e-6, a[2] - a[0])
    width_b = max(1e-6, b[2] - b[0])
    return max(overlap / width_a, overlap / width_b)


def _labels_from_caption(caption: str | None) -> list[str]:
    text = unicodedata.normalize("NFKC", caption or "")
    return [label.lower() for label in _SUBFIGURE_LABEL_RE.findall(text)]


def _infer_subfigure_labels_from_page(
    raw: ExtractionResult,
    page_number: int,
    fig_num: int,
) -> list[str]:
    pattern = re.compile(rf"fig\.?\s*{fig_num}\s*\(([a-z])\)", re.IGNORECASE)
    labels: list[str] = []
    for page in raw.pages:
        if abs(page.page_number - page_number) > 2:
            continue
        for block in page.blocks:
            for match in pattern.finditer(block.text or ""):
                label = match.group(1).lower()
                if label not in labels:
                    labels.append(label)
    return labels


def _expand_figure_caption(
    cap: CaptionCandidate,
    raw: ExtractionResult,
    figure_caps_on_page: list[CaptionCandidate],
) -> str:
    fig_num = parse_figure_number(cap.text or "") or _parse_figure_number(cap.text or "") or 0
    parts: list[str] = []
    seed = (cap.text or "").strip()
    if seed:
        parts.append(seed)
    physical_lines = sum(1 for line in seed.splitlines() if line.strip())
    if not cap.bbox or len(cap.bbox) < 4:
        return "\n".join(part for part in parts if part).strip()
    cap_y1 = float(cap.bbox[3])
    page = next((p for p in raw.pages if p.page_number == cap.page_number), None)
    if not page:
        return "\n".join(part for part in parts if part).strip()
    cap_center_x = (cap.bbox[0] + cap.bbox[2]) / 2.0
    page_width = float(page.width or 612.0)
    for block in page.blocks:
        if block.type != "text" or not (block.text or "").strip() or not block.bbox:
            continue
        block_top = float(block.bbox[1])
        if block_top < cap_y1 - 1.0:
            continue
        if block_top > cap_y1 + 130.0:
            break
        block_center_x = (block.bbox[0] + block.bbox[2]) / 2.0
        if abs(block_center_x - cap_center_x) > page_width * 0.32:
            continue
        for line in (block.text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if figure_caption_boundary_line(stripped, fig_num):
                return "\n".join(part for part in parts if part).strip()
            if _FIGURE_CAPTION_START_RE.match(stripped) and not re.match(
                rf"^fig(?:ure)?\.?\s*{fig_num}\b",
                stripped,
                re.IGNORECASE,
            ):
                return "\n".join(part for part in parts if part).strip()
            if block_top > cap_y1 + 0.5:
                if physical_lines >= _MAX_FIGURE_CAPTION_LINES:
                    break
                if not figure_caption_continuation_line(stripped, fig_num):
                    break
            if stripped not in (parts[-1] if parts else ""):
                parts.append(stripped)
                physical_lines += 1
    return "\n".join(part for part in parts if part).strip()


def _image_bboxes_on_page(page: pymupdf.Page) -> list[list[float]]:
    bboxes: list[list[float]] = []
    seen: set[tuple[float, float, float, float]] = set()
    try:
        for xref, *_rest in page.get_images(full=True):
            for rect in page.get_image_rects(xref):
                bb = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
                key = tuple(round(v, 1) for v in bb)
                if key in seen:
                    continue
                seen.add(key)
                bboxes.append(bb)
    except Exception:
        pass
    try:
        for block in page.get_text("dict").get("blocks") or []:
            if block.get("type") != 1:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            bb = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
            key = tuple(round(v, 1) for v in bb)
            if key in seen:
                continue
            seen.add(key)
            bboxes.append(bb)
    except Exception:
        pass
    return bboxes


def _populate_subfigures_from_page(
    page: pymupdf.Page,
    caption: str | None,
    primary_bbox: list[float],
    *,
    caption_bbox: list[float] | None = None,
    prior_caption_bbox: list[float] | None = None,
) -> tuple[list[float], list[ExtractedSubfigure]]:
    labels = _labels_from_caption(caption)
    if not labels:
        labels = subfigure_labels(caption)

    anchor = primary_bbox if len(primary_bbox) >= 4 else (caption_bbox or primary_bbox)
    cap_y0 = float(caption_bbox[1]) if caption_bbox and len(caption_bbox) >= 4 else float(anchor[1])
    fig_y0 = float(anchor[1])
    fig_y1 = float(anchor[3])
    band_top = min(fig_y0, cap_y0) - 100.0
    band_bottom = cap_y0 + 25.0
    if prior_caption_bbox and len(prior_caption_bbox) >= 4:
        band_top = max(band_top, float(prior_caption_bbox[3]) - 5.0)

    selected: list[list[float]] = []
    for bbox in _image_bboxes_on_page(page):
        if _area(bbox) < _MIN_SUBFIGURE_AREA:
            continue
        if bbox[3] > band_bottom or bbox[1] < band_top:
            continue
        if _horizontal_overlap_ratio(bbox, anchor) < 0.1:
            if caption_bbox and _horizontal_overlap_ratio(bbox, caption_bbox) < 0.1:
                continue
        if any(_iou(bbox, existing) > 0.9 for existing in selected):
            continue
        selected.append(list(bbox))

    if len(selected) < 2 and _area(primary_bbox) >= _MIN_SUBFIGURE_AREA:
        if not selected:
            selected = [list(primary_bbox)]

    expected = len(labels) if labels else 0
    if len(selected) < 2 and expected >= 2:
        for bbox in _image_bboxes_on_page(page):
            if _area(bbox) < _MIN_SUBFIGURE_AREA:
                continue
            if bbox[3] > band_bottom + 120 or bbox[1] < band_top - 120:
                continue
            if _horizontal_overlap_ratio(bbox, anchor) < 0.08:
                continue
            if any(_iou(bbox, existing) > 0.9 for existing in selected):
                continue
            selected.append(list(bbox))
        selected.sort(key=lambda bb: (bb[1], bb[0]))

    if len(selected) < 2 and expected < 2:
        return primary_bbox, []

    selected.sort(key=lambda bb: (bb[1], bb[0]))
    deduped: list[list[float]] = []
    for bbox in selected:
        if any(_iou(bbox, existing) > 0.75 for existing in deduped):
            continue
        deduped.append(bbox)
    selected = deduped
    if not labels or len(labels) < len(selected):
        labels = [chr(ord("a") + index) for index in range(len(selected))]
    if labels and len(selected) > len(labels):
        selected = selected[: len(labels)]

    composite = selected[0]
    for bbox in selected[1:]:
        composite = _union_bbox(composite, bbox)

    subfigures = [
        ExtractedSubfigure(label=labels[index], bbox=selected[index])
        for index in range(min(len(labels), len(selected)))
    ]
    return composite, subfigures


def _engine_label(source: str) -> str:
    return {
        "raster_image": "pymupdf_embedded",
        "layout_image_block": "pymupdf_layout_block",
        "vector_drawings": "pymupdf_vector_cluster",
        "whitespace_gap": "pymupdf_pixmap",
        "whitespace_zone": "pymupdf_pixmap",
        "caption_zone_render": "pymupdf_pixmap",
        "caption_column_slice": "pymupdf_pixmap",
    }.get(source, "pymupdf_pixmap")


def extract_figures(

    pdf_path: Path,

    raw: ExtractionResult,

    captions: list[CaptionCandidate],

    *,

    figures_dir: Path | None = None,

    path_prefix: str = "figures",

) -> list[ExtractedFigure]:

    """Extract numbered FIGURE objects by matching captions to regions above each caption."""

    figures: list[ExtractedFigure] = []

    if not pdf_path.is_file():

        return figures



    figure_caps = [
        c for c in figure_caption_candidates(captions) if _parse_figure_number(c.text) is not None
    ]
    figure_caps.sort(key=lambda c: _parse_figure_number(c.text) or 0)

    doc = pymupdf.open(str(pdf_path))

    try:

        used_regions: set[tuple[int, tuple[float, float, float, float]]] = set()
        used_figure_numbers: set[int] = set()
        used_bboxes: list[list[float]] = []

        caps_by_page: dict[int, list[CaptionCandidate]] = {}
        for cap in figure_caps:
            caps_by_page.setdefault(cap.page_number, []).append(cap)
        for page_caps in caps_by_page.values():
            page_caps.sort(key=lambda c: c.bbox[1] if c.bbox else 0.0)

        for cap in figure_caps:
            fig_num = _parse_figure_number(cap.text)
            if fig_num is None or fig_num in used_figure_numbers:
                continue
            used_figure_numbers.add(fig_num)

            page_caps = caps_by_page.get(cap.page_number, [])
            prior_cap: CaptionCandidate | None = None
            for candidate in page_caps:
                if candidate is cap:
                    break
                prior_cap = candidate

            page = doc[cap.page_number - 1]
            full_caption = _expand_figure_caption(cap, raw, page_caps)
            page_model = next((p for p in raw.pages if p.page_number == cap.page_number), None)
            if page_model:
                pair_line = find_subfigure_pair_line_near_caption(
                    page_model.blocks,
                    cap.bbox,
                    page_width=float(page_model.width or 612.0),
                )
                if pair_line and pair_line not in full_caption:
                    full_caption = f"{full_caption.rstrip()}\n{pair_line}"
            inferred_labels = _infer_subfigure_labels_from_page(raw, cap.page_number, fig_num)
            if inferred_labels and not _labels_from_caption(full_caption):
                full_caption = f"{full_caption}\n" + " ".join(
                    f"({label})" for label in inferred_labels
                )

            page_h = float(page_model.height if page_model else page.rect.height)

            text_bboxes = _text_block_bboxes(raw, cap.page_number)



            regions = collect_figure_regions(page, text_block_bboxes=text_bboxes)

            whitespace = _whitespace_regions_above_caption(

                page, cap.bbox, text_block_bboxes=text_bboxes

            )

            matched = match_caption_to_region(
                cap,
                regions,
                extra_whitespace=whitespace,
                used_bboxes=used_bboxes,
                prior_cap=prior_cap,
            )

            if matched is None:
                zone_cand = zone_render_candidate(cap)
                if _area(zone_cand.bbox) >= 8_000:
                    matched = MatchedFigure(
                        caption=cap,
                        region=zone_cand,
                        gap=cap.bbox[1] - zone_cand.bbox[3],
                        score=40.0,
                    )
                else:
                    logger.debug(
                        "No figure region for caption page=%s text=%s",
                        cap.page_number,
                        cap.text[:60],
                    )
                    continue



            region_pool = [
                *regions,
                *(whitespace or []),
            ]
            bbox, subfigure_payload = resolve_subfigure_group(
                full_caption,
                matched.region.bbox,
                region_pool,
                caption_bbox=list(cap.bbox),
            )
            subfigures: list[ExtractedSubfigure] = []
            if subfigure_payload:
                subfigures = [
                    ExtractedSubfigure(label=str(item["label"]), bbox=list(item["bbox"]))
                    for item in subfigure_payload
                ]
            label_count = len(_labels_from_caption(full_caption))
            if label_count >= 2:
                label_count = min(label_count, 3)
            if len(subfigures) < max(2, label_count):
                prior_bbox = list(prior_cap.bbox) if prior_cap and prior_cap.bbox else None
                bbox, discovered = _populate_subfigures_from_page(
                    page,
                    full_caption,
                    bbox,
                    caption_bbox=list(cap.bbox),
                    prior_caption_bbox=prior_bbox,
                )
                if discovered:
                    if label_count >= 2:
                        subfigures = discovered[:label_count]
                    else:
                        subfigures = discovered
            if not subfigures:
                labels = _labels_from_caption(full_caption) or ["a"]
                subfigures = [ExtractedSubfigure(label=labels[0], bbox=bbox)]
                logger.debug(
                    "Subfigure image clustering failed for fig %s page %s; using single panel.",
                    fig_num,
                    cap.page_number,
                )
            expected_labels = _labels_from_caption(full_caption)
            if expected_labels and len(subfigures) > len(expected_labels):
                subfigures = subfigures[: len(expected_labels)]
            subfigures_out: list[ExtractedSubfigure] | None = subfigures or None

            key = (cap.page_number, tuple(round(v, 1) for v in bbox))

            if key in used_regions:

                continue

            used_regions.add(key)
            used_bboxes.append(bbox)

            figure_id = f"figure_{fig_num}"
            file_stem = f"fig_{fig_num}"

            rel_path: str | None = None

            image_saved = False

            xref = matched.region.xref
            engine = _engine_label(matched.region.source)

            if figures_dir is not None:

                rel_path = f"{path_prefix}/{file_stem}.png"

                out_path = figures_dir / f"{file_stem}.png"

                image_saved = render_region_png(page, bbox, out_path)

                if not image_saved and xref is not None:

                    image_saved = _save_pixmap(doc, xref, out_path)



            figures.append(

                ExtractedFigure(

                    figure_id=figure_id,

                    id=figure_id,

                    figure_number=fig_num,

                    subfigures=subfigures_out,

                    page_number=cap.page_number,

                    bbox=bbox,

                    xref=xref,

                    image_path=rel_path if image_saved else None,

                    caption=full_caption,

                    caption_bbox=list(cap.bbox),

                    extraction_engine=engine,

                    figure_kind="figure",

                    extraction_quality=FigureExtractionQuality(

                        image_extracted=image_saved,

                        caption_detected=True,

                        confidence=min(0.98, 0.55 + matched.score / 120.0),

                        classification="figure",

                        warnings=[] if image_saved else ["render_failed"],

                    ),

                )

            )



        if not figure_caps:

            figures.extend(

                _legacy_orphan_images(doc, raw, captions, figures_dir, path_prefix)

            )

    finally:

        doc.close()



    return figures





def _legacy_orphan_images(

    doc: pymupdf.Document,

    raw: ExtractionResult,

    captions: list[CaptionCandidate],

    figures_dir: Path | None,

    path_prefix: str = "figures",

) -> list[ExtractedFigure]:

    """Fallback when no strict figure captions exist (e.g. synthetic test PDFs)."""

    from app.pipeline.phase1.captions import nearest_caption



    figures: list[ExtractedFigure] = []

    seen: set[tuple[int, tuple[float, float, float, float]]] = set()
    used_nums: set[int] = set()



    for page_model in raw.pages:

        page = doc[page_model.page_number - 1]

        page_h = float(page_model.height or page.rect.height)

        for xref, *_rest in page.get_images(full=True):

            for rect in page.get_image_rects(xref):

                bbox = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]

                if _area(bbox) < 5_000:

                    continue

                key = (page_model.page_number, tuple(round(v, 1) for v in bbox))

                if key in seen:

                    continue

                seen.add(key)

                cap = nearest_caption(

                    captions,

                    page_number=page_model.page_number,

                    bbox=bbox,

                    caption_type="figure",

                    max_vertical_gap=160.0,

                )

                if cap is None:

                    continue

                kind = _classify_unmatched(

                    page_model.page_number,

                    page_h,

                    bbox,

                    raw.document.page_count,

                )

                if kind in {"decorative", "logo", "author_photo"}:

                    continue

                fig_num = _parse_figure_number(cap.text) if cap else None
                if fig_num is None:
                    continue
                if fig_num in used_nums:
                    continue
                used_nums.add(fig_num)

                figure_id = f"figure_{fig_num}"
                file_stem = f"fig_{fig_num}"

                image_saved = False

                rel_path: str | None = None

                if figures_dir is not None:

                    rel_path = f"{path_prefix}/{file_stem}.png"

                    image_saved = render_region_png(page, bbox, figures_dir / f"{file_stem}.png")

                    if not image_saved:

                        image_saved = _save_pixmap(doc, int(xref), figures_dir / f"{file_stem}.png")

                figures.append(

                    ExtractedFigure(

                        figure_id=figure_id,

                        id=figure_id,

                        figure_number=fig_num,

                        page_number=page_model.page_number,

                        bbox=bbox,

                        xref=int(xref),

                        image_path=rel_path if image_saved else None,

                        caption=cap.text if cap else None,

                        figure_kind=kind,

                        extraction_quality=FigureExtractionQuality(

                            image_extracted=image_saved,

                            caption_detected=bool(cap),

                            confidence=0.65,

                            classification=kind,

                        ),

                    )

                )

    return figures


