"""Multi-signal figure region detection and caption matching (IEEE-style)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.pipeline.phase1.captions import CaptionCandidate
from app.services.layout.semantic_patterns import FIGURE_CAPTION_RE, first_line, normalize_text

STRICT_FIGURE_CAPTION_RE = re.compile(
    r"^(?:FIGURE|Fig\.)\s+\d+[\.\:]",
    re.IGNORECASE,
)

MIN_RASTER_AREA = 5_000.0
MIN_RASTER_HEIGHT = 50.0
MIN_VECTOR_CLUSTER_AREA = 5_000.0
MIN_WHITESPACE_SIDE = 100.0
CAPTION_SEARCH_ABOVE = 280.0
CAPTION_MAX_GAP = 180.0
MIN_H_OVERLAP = 0.50

RENDER_DPI = 300


@dataclass
class FigureRegionCandidate:
    bbox: list[float]
    source: str
    xref: int | None = None
    area: float = 0.0


@dataclass
class MatchedFigure:
    caption: CaptionCandidate
    region: FigureRegionCandidate
    gap: float
    score: float


def _area(bbox: list[float]) -> float:
    if len(bbox) < 4:
        return 0.0
    return max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))


def _union_bbox(a: list[float], b: list[float]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _horizontal_overlap_ratio(fig_bbox: list[float], cap_bbox: list[float]) -> float:
    if len(fig_bbox) < 4 or len(cap_bbox) < 4:
        return 0.0
    left = max(fig_bbox[0], cap_bbox[0])
    right = min(fig_bbox[2], cap_bbox[2])
    overlap = max(0.0, right - left)
    fig_w = max(1e-6, fig_bbox[2] - fig_bbox[0])
    cap_w = max(1e-6, cap_bbox[2] - cap_bbox[0])
    return max(overlap / fig_w, overlap / cap_w)


def _intersects_zone(bbox: list[float], zone: list[float]) -> bool:
    if len(bbox) < 4 or len(zone) < 4:
        return False
    x0 = max(bbox[0], zone[0])
    y0 = max(bbox[1], zone[1])
    x1 = min(bbox[2], zone[2])
    y1 = min(bbox[3], zone[3])
    return x1 > x0 and y1 > y0


_INLINE_FIGURE_REF_RE = re.compile(
    r"\b(?:shows|illustrates|depicts|presents|summarizes|compares)\b",
    re.IGNORECASE,
)


def is_strict_figure_caption(text: str) -> bool:
    line = first_line(normalize_text(text))
    if STRICT_FIGURE_CAPTION_RE.match(line):
        return True
    if FIGURE_CAPTION_RE.match(line):
        if _INLINE_FIGURE_REF_RE.search(line):
            return False
        if len(line) > 120:
            return False
        return True
    return False


def figure_caption_candidates(captions: list[CaptionCandidate]) -> list[CaptionCandidate]:
    out: list[CaptionCandidate] = []
    for cap in captions:
        if cap.caption_type not in {"figure", "unknown"}:
            continue
        if is_strict_figure_caption(cap.text):
            out.append(cap)
    out.sort(key=lambda c: (c.page_number, c.bbox[1]))
    return out


def _cluster_drawing_rects(rects: list[list[float]], *, pad: float = 8.0) -> list[list[float]]:
    clusters: list[list[float]] = []
    for rect in rects:
        if _area(rect) < MIN_VECTOR_CLUSTER_AREA:
            continue
        merged = False
        for i, existing in enumerate(clusters):
            ex = [
                existing[0] - pad,
                existing[1] - pad,
                existing[2] + pad,
                existing[3] + pad,
            ]
            if _intersects_zone(rect, ex):
                clusters[i] = _union_bbox(existing, rect)
                merged = True
                break
        if not merged:
            clusters.append(list(rect))
    return clusters


def _drawing_regions(page: pymupdf.Page) -> list[FigureRegionCandidate]:
    rects: list[list[float]] = []
    try:
        for path in page.get_drawings():
            rect = path.get("rect")
            if rect is None:
                continue
            if hasattr(rect, "x0"):
                r = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
            else:
                r = [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]
            if _area(r) >= 500:
                rects.append(r)
    except Exception:
        return []
    clusters = _cluster_drawing_rects(rects)
    return [
        FigureRegionCandidate(bbox=c, source="vector_drawings", area=_area(c))
        for c in clusters
        if _area(c) >= MIN_VECTOR_CLUSTER_AREA
    ]


def _raster_regions(page: pymupdf.Page) -> list[FigureRegionCandidate]:
    out: list[FigureRegionCandidate] = []
    seen: set[tuple[float, float, float, float]] = set()
    try:
        for xref, *_rest in page.get_images(full=True):
            for rect in page.get_image_rects(xref):
                bbox = [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
                h = bbox[3] - bbox[1]
                a = _area(bbox)
                if a < MIN_RASTER_AREA or h < MIN_RASTER_HEIGHT:
                    continue
                key = tuple(round(v, 1) for v in bbox)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    FigureRegionCandidate(
                        bbox=bbox,
                        source="raster_image",
                        xref=int(xref),
                        area=a,
                    )
                )
    except Exception:
        pass
    return out


def _dict_image_blocks(page: pymupdf.Page) -> list[FigureRegionCandidate]:
    out: list[FigureRegionCandidate] = []
    data = page.get_text("dict")
    for block in data.get("blocks") or []:
        if block.get("type") != 1:
            continue
        bbox = block.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        b = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        a = _area(b)
        if a < MIN_RASTER_AREA:
            continue
        out.append(FigureRegionCandidate(bbox=b, source="layout_image_block", area=a))
    return out


def _whitespace_regions_above_caption(
    page: pymupdf.Page,
    cap_bbox: list[float],
    *,
    text_block_bboxes: list[list[float]],
) -> list[FigureRegionCandidate]:
    if len(cap_bbox) < 4:
        return []
    cap_x0, cap_y0, cap_x1, _ = cap_bbox
    zone_top = max(36.0, cap_y0 - CAPTION_SEARCH_ABOVE)
    zone_bottom = cap_y0 - 5.0
    if zone_bottom - zone_top < MIN_WHITESPACE_SIDE:
        return []

    col_x0 = max(36.0, cap_x0 - 40)
    col_x1 = min(page.rect.width - 36, cap_x1 + 40)

    occupied: list[list[float]] = []
    for bb in text_block_bboxes:
        if len(bb) < 4:
            continue
        if bb[3] < zone_top or bb[1] > zone_bottom:
            continue
        if bb[2] < col_x0 or bb[0] > col_x1:
            continue
        occupied.append(bb)

    if not occupied:
        candidate = [col_x0, zone_top, col_x1, zone_bottom]
        if _area(candidate) >= MIN_WHITESPACE_SIDE * MIN_WHITESPACE_SIDE:
            return [
                FigureRegionCandidate(
                    bbox=candidate,
                    source="whitespace_zone",
                    area=_area(candidate),
                )
            ]
        return []

    occupied.sort(key=lambda b: b[1])
    gaps: list[FigureRegionCandidate] = []
    cursor_y = zone_top
    for bb in occupied:
        if bb[1] > cursor_y + MIN_WHITESPACE_SIDE:
            gap_bbox = [col_x0, cursor_y, col_x1, min(bb[1], zone_bottom)]
            if gap_bbox[3] - gap_bbox[1] >= MIN_WHITESPACE_SIDE:
                w = gap_bbox[2] - gap_bbox[0]
                if w >= MIN_WHITESPACE_SIDE:
                    gaps.append(
                        FigureRegionCandidate(
                            bbox=gap_bbox,
                            source="whitespace_gap",
                            area=_area(gap_bbox),
                        )
                    )
        cursor_y = max(cursor_y, bb[3])
    if zone_bottom - cursor_y >= MIN_WHITESPACE_SIDE:
        gap_bbox = [col_x0, cursor_y, col_x1, zone_bottom]
        gaps.append(
            FigureRegionCandidate(
                bbox=gap_bbox,
                source="whitespace_gap",
                area=_area(gap_bbox),
            )
        )
    return gaps


def collect_figure_regions(
    page: pymupdf.Page,
    *,
    text_block_bboxes: list[list[float]] | None = None,
) -> list[FigureRegionCandidate]:
    text_block_bboxes = text_block_bboxes or []
    regions: list[FigureRegionCandidate] = []
    regions.extend(_raster_regions(page))
    regions.extend(_dict_image_blocks(page))
    regions.extend(_drawing_regions(page))
    return _dedupe_regions(regions)


def _dedupe_regions(
    regions: list[FigureRegionCandidate],
    *,
    iou_threshold: float = 0.55,
) -> list[FigureRegionCandidate]:
    kept: list[FigureRegionCandidate] = []
    for cand in sorted(regions, key=lambda r: r.area, reverse=True):
        if any(_iou(cand.bbox, k.bbox) > iou_threshold for k in kept):
            continue
        kept.append(cand)
    return kept


def _iou(a: list[float], b: list[float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def caption_search_zone(cap_bbox: list[float]) -> list[float]:
    cap_y0 = cap_bbox[1]
    return [
        cap_bbox[0] - 60,
        max(36.0, cap_y0 - CAPTION_SEARCH_ABOVE),
        cap_bbox[2] + 60,
        cap_y0 - 5,
    ]


def zone_render_candidate(cap: CaptionCandidate) -> FigureRegionCandidate:
    zone = caption_search_zone(cap.bbox)
    return FigureRegionCandidate(
        bbox=zone,
        source="caption_zone_render",
        area=_area(zone),
    )


def _score_caption_region_match(
    cap: CaptionCandidate,
    reg: FigureRegionCandidate,
    *,
    zone: list[float],
) -> MatchedFigure | None:
    if len(cap.bbox) < 4:
        return None
    cap_y0 = cap.bbox[1]
    if not _intersects_zone(reg.bbox, zone):
        return None
    if reg.bbox[3] > cap_y0 + 8:
        return None
    gap = cap_y0 - reg.bbox[3]
    if gap < -10 or gap > CAPTION_MAX_GAP:
        return None
    h_ov = _horizontal_overlap_ratio(reg.bbox, cap.bbox)
    if h_ov < MIN_H_OVERLAP:
        return None
    score = h_ov * 100.0 - abs(gap) * 0.15 + min(reg.area, 80_000) / 800.0
    if reg.source == "raster_image":
        score += 8.0
    if reg.source == "layout_image_block":
        score += 6.0
    if reg.source in {"whitespace_zone", "caption_zone_render"}:
        score -= 12.0
    return MatchedFigure(caption=cap, region=reg, gap=gap, score=score)


def match_caption_to_regions(
    cap: CaptionCandidate,
    regions: list[FigureRegionCandidate],
    *,
    extra_whitespace: list[FigureRegionCandidate] | None = None,
) -> list[MatchedFigure]:
    if len(cap.bbox) < 4:
        return []
    zone = caption_search_zone(cap.bbox)
    pool = list(regions)
    if extra_whitespace:
        pool.extend(extra_whitespace)
    pool = _dedupe_regions(pool)

    matches: list[MatchedFigure] = []
    for reg in pool:
        scored = _score_caption_region_match(cap, reg, zone=zone)
        if scored is not None:
            matches.append(scored)
    matches.sort(key=lambda m: m.score, reverse=True)
    return matches


def column_slice_above_caption(
    cap: CaptionCandidate,
    *,
    prior_cap: CaptionCandidate | None = None,
    page_top: float = 36.0,
) -> list[float]:
    """Vertical strip in the caption column between the prior caption and this one."""
    if len(cap.bbox) < 4:
        return []
    top = page_top
    if prior_cap is not None and len(prior_cap.bbox) >= 4 and prior_cap.page_number == cap.page_number:
        top = max(page_top, prior_cap.bbox[3] + 4.0)
    bottom = max(top + 40.0, cap.bbox[1] - 4.0)
    x_pad = 24.0
    return [
        max(36.0, cap.bbox[0] - x_pad),
        top,
        cap.bbox[2] + x_pad,
        bottom,
    ]


def match_caption_to_region(
    cap: CaptionCandidate,
    regions: list[FigureRegionCandidate],
    *,
    extra_whitespace: list[FigureRegionCandidate] | None = None,
    used_bboxes: list[list[float]] | None = None,
    iou_threshold: float = 0.8,
    prior_cap: CaptionCandidate | None = None,
) -> MatchedFigure | None:
    matches = match_caption_to_regions(cap, regions, extra_whitespace=extra_whitespace)
    for matched in matches:
        if used_bboxes and any(_iou(matched.region.bbox, bbox) > iou_threshold for bbox in used_bboxes):
            continue
        return matched
    if matches and used_bboxes:
        slice_bbox = column_slice_above_caption(cap, prior_cap=prior_cap)
        if slice_bbox and _area(slice_bbox) >= 8_000:
            return MatchedFigure(
                caption=cap,
                region=FigureRegionCandidate(
                    bbox=slice_bbox,
                    source="caption_column_slice",
                    area=_area(slice_bbox),
                ),
                gap=cap.bbox[1] - slice_bbox[3],
                score=35.0,
            )
    return matches[0] if matches else None


def composite_subfigure_bbox(
    cap: CaptionCandidate,
    primary_bbox: list[float],
    regions: list[FigureRegionCandidate],
    *,
    extra_whitespace: list[FigureRegionCandidate] | None = None,
) -> list[float]:
    from app.pipeline.phase1.caption_parse import subfigure_labels

    labels = subfigure_labels(cap.text)
    if len(labels) <= 1:
        return primary_bbox
    zone = caption_search_zone(cap.bbox)
    pool = list(regions)
    if extra_whitespace:
        pool.extend(extra_whitespace)
    merged = list(primary_bbox)
    cap_y0 = cap.bbox[1]
    for reg in pool:
        if _iou(reg.bbox, primary_bbox) > 0.92:
            continue
        if not _intersects_zone(reg.bbox, zone):
            continue
        if reg.bbox[3] > cap_y0 + 10:
            continue
        gap = cap_y0 - reg.bbox[3]
        if gap < -10 or gap > CAPTION_MAX_GAP:
            continue
        if _horizontal_overlap_ratio(reg.bbox, cap.bbox) < 0.25:
            continue
        merged = _union_bbox(merged, reg.bbox)
    return merged


def render_region_png(page: pymupdf.Page, bbox: list[float], path: Path) -> bool:
    if len(bbox) < 4:
        return False
    try:
        zoom = RENDER_DPI / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        clip = pymupdf.Rect(bbox)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(path))
        return True
    except Exception:
        return False
