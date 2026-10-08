"""BBox geometry helpers (PyMuPDF top-left origin)."""

from __future__ import annotations


def bbox_area(bbox: list[float]) -> float:
    if len(bbox) < 4:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def bbox_height(bbox: list[float]) -> float:
    if len(bbox) < 4:
        return 0.0
    return max(0.0, bbox[3] - bbox[1])


def intersection_area(a: list[float], b: list[float]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def iou(a: list[float], b: list[float]) -> float:
    inter = intersection_area(a, b)
    if inter <= 0:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def overlap_ratio_of_a(a: list[float], b: list[float]) -> float:
    """Fraction of bbox `a` that overlaps `b`."""
    area_a = bbox_area(a)
    if area_a <= 0:
        return 0.0
    return intersection_area(a, b) / area_a


def overlap_ratio_of_smaller(a: list[float], b: list[float]) -> float:
    """Intersection area divided by the smaller bbox area."""
    smaller = min(bbox_area(a), bbox_area(b))
    if smaller <= 0:
        return 0.0
    return intersection_area(a, b) / smaller


def horizontal_overlap_ratio(a: list[float], b: list[float]) -> float:
    if len(a) < 4 or len(b) < 4:
        return 0.0
    left = max(a[0], b[0])
    right = min(a[2], b[2])
    width_a = max(1e-6, a[2] - a[0])
    return max(0.0, right - left) / width_a


def camelot_bbox_to_fitz(bbox: tuple[float, ...], page_height: float) -> list[float]:
    """Camelot PDF coords (origin bottom-left) -> PyMuPDF (origin top-left)."""
    x0, y0, x1, y1 = bbox
    return [float(x0), float(page_height - y1), float(x1), float(page_height - y0)]


def fitz_bbox_to_camelot_area(bbox: list[float], page_height: float) -> str:
    """PyMuPDF bbox -> Camelot ``table_areas`` string (left,bottom,right,top)."""
    x0, y0, x1, y1 = bbox
    return f"{x0},{page_height - y1},{x1},{page_height - y0}"


def image_bbox_to_fitz(
    bbox: tuple[float, ...] | list[float],
    page_width: float,
    page_height: float,
    image_width: int,
    image_height: int,
) -> list[float]:
    """Map pixel bbox from rendered page image to PDF points."""
    if image_width <= 0 or image_height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    sx = page_width / image_width
    sy = page_height / image_height
    x0, y0, x1, y1 = bbox
    return [x0 * sx, y0 * sy, x1 * sx, y1 * sy]


def column_bounds_for_x(x: float, page_width: float, margin: float = 36.0) -> tuple[float, float]:
    """Heuristic single-column horizontal bounds for academic two-column PDFs."""
    mid = page_width / 2.0
    gutter = 12.0
    if x < mid - 20:
        return margin, mid - gutter
    return mid + gutter, page_width - margin
