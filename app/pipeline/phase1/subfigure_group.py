"""Group multi-panel figure regions using caption (a)(b)(c) labels."""

from __future__ import annotations

from app.pipeline.phase1.caption_parse import subfigure_labels
from app.pipeline.phase1.figure_detection import FigureRegionCandidate, _area, _horizontal_overlap_ratio, _union_bbox

_SUBFIGURE_Y_WINDOW = 350.0
_MIN_PANEL_AREA = 2_500.0


def _y_distance(a: list[float], b: list[float]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 1e9
    if a[3] < b[1]:
        return b[1] - a[3]
    if b[3] < a[1]:
        return a[1] - b[3]
    return 0.0


def _x_overlap(a: list[float], b: list[float]) -> bool:
    return _horizontal_overlap_ratio(a, b) >= 0.2


def resolve_subfigure_group(
    caption: str | None,
    primary_bbox: list[float],
    regions: list[FigureRegionCandidate],
    *,
    caption_bbox: list[float] | None = None,
) -> tuple[list[float], list[dict[str, list[float] | str]]]:
    """
    Return composite bbox and per-panel entries ``{label, bbox}``.

    When the caption lists multiple (a)(b)(c) panels, merge nearby image regions on
    the same page column into one export region.
    """
    labels = subfigure_labels(caption)
    anchor = caption_bbox if caption_bbox and len(caption_bbox) >= 4 else primary_bbox
    if len(labels) < 2:
        return primary_bbox, []

    cap_y0 = anchor[1] if len(anchor) >= 4 else primary_bbox[1]
    band_top = max(0.0, cap_y0 - _SUBFIGURE_Y_WINDOW)

    selected: list[list[float]] = []
    for reg in regions:
        if _area(reg.bbox) < _MIN_PANEL_AREA:
            continue
        if reg.bbox[3] > cap_y0 + 12:
            continue
        if reg.bbox[1] < band_top:
            continue
        if not _x_overlap(reg.bbox, anchor) and not _x_overlap(reg.bbox, primary_bbox):
            continue
        bbox = list(reg.bbox)
        if any(all(abs(bbox[i] - s[i]) < 1.5 for i in range(4)) for s in selected):
            continue
        selected.append(bbox)
    if not selected:
        selected = [list(primary_bbox)]
    elif all(_area(b) < _area(primary_bbox) * 1.05 for b in selected):
        selected.append(list(primary_bbox))

    selected.sort(key=lambda b: (b[1], b[0]))
    composite = selected[0]
    for bbox in selected[1:]:
        composite = _union_bbox(composite, bbox)

    subfigures: list[dict[str, list[float] | str]] = []
    for index, bbox in enumerate(selected):
        label = labels[index] if index < len(labels) else labels[-1]
        subfigures.append({"label": label, "bbox": bbox})

    if len(subfigures) < len(labels) and len(composite) >= 4:
        panel_height = (composite[3] - composite[1]) / len(labels)
        subfigures = []
        for index, label in enumerate(labels):
            y0 = composite[1] + index * panel_height
            y1 = composite[1] + (index + 1) * panel_height
            subfigures.append(
                {
                    "label": label,
                    "bbox": [composite[0], y0, composite[2], y1],
                }
            )

    return composite, subfigures
