"""OCR fallback for image/vector tables without a text layer."""

from __future__ import annotations

import logging
from collections import defaultdict

import numpy as np
import pymupdf

from app.pipeline.table_extraction.postprocess import sanitize_cell

logger = logging.getLogger(__name__)

_reader = None


def _get_reader():
    global _reader
    if _reader is not None:
        return _reader
    try:
        import easyocr
    except ImportError:
        return None
    try:
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception as exc:
        logger.debug("EasyOCR init failed: %s", exc)
        return None
    return _reader


def ocr_bbox_to_grid(page: pymupdf.Page, bbox: list[float]) -> tuple[list[list[str]], list[float]]:
    if len(bbox) < 4:
        return [], bbox
    reader = _get_reader()
    if reader is None:
        return [], bbox

    clip = pymupdf.Rect(bbox)
    if clip.height < 20 or clip.width < 40:
        return [], bbox

    zoom = 2.5
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]

    try:
        detections = reader.readtext(img, paragraph=False)
    except Exception as exc:
        logger.debug("OCR read failed: %s", exc)
        return [], bbox

    if not detections:
        return [], bbox

    scale = 1.0 / zoom
    words: list[tuple[float, float, float, float, str]] = []
    for det in detections:
        box, text, _conf = det[0], det[1], det[2]
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0 = clip.x0 + min(xs) * scale
        y0 = clip.y0 + min(ys) * scale
        x1 = clip.x0 + max(xs) * scale
        y1 = clip.y0 + max(ys) * scale
        text = sanitize_cell(text)
        if text:
            words.append((x0, y0, x1, y1, text))

    if len(words) < 4:
        return [], bbox

    lines: dict[float, list[tuple]] = defaultdict(list)
    for w in words:
        key = round(w[1] / 6.0) * 6.0
        lines[key].append(w)

    row_cells: list[list[str]] = []
    y_coords: list[float] = []
    x_coords: list[float] = []
    for y in sorted(lines):
        line = sorted(lines[y], key=lambda t: t[0])
        cells: list[str] = []
        buf = [line[0][4]]
        prev_x1 = line[0][2]
        for item in line[1:]:
            if item[0] - prev_x1 > 22:
                cells.append(" ".join(buf))
                buf = [item[4]]
            else:
                buf.append(item[4])
            prev_x1 = item[2]
        cells.append(" ".join(buf))
        if any(c.strip() for c in cells):
            row_cells.append([sanitize_cell(c) for c in cells])
            y_coords.append(y)
            for item in line:
                x_coords.extend([item[0], item[2]])

    if len(row_cells) < 2:
        return [], bbox

    ncol = max(len(r) for r in row_cells)
    if ncol < 2:
        return [], bbox

    normalized = [r + [""] * (ncol - len(r)) for r in row_cells]
    tight = [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]
    return normalized, tight
