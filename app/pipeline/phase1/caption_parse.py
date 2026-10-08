"""Caption text normalization and figure/table label parsing."""

from __future__ import annotations

import re
import unicodedata

_FIGURE_NUM_STRICT_RE = re.compile(r"Fig\.\s*(\d+)\.", re.IGNORECASE)
_FIGURE_NUM_LOOSE_RE = re.compile(r"fig(?:ure)?\.?\s*(\d+)", re.IGNORECASE)
_SUBFIGURE_LABEL_RE = re.compile(r"\(([a-z])\)", re.IGNORECASE)
_FIGURE_CAPTION_LINE_RE = re.compile(r"^\s*Fig\.\s*\d+\.", re.IGNORECASE)
_SECTION_HEADING_STOP_RE = re.compile(
    r"^(?:[IVXLC]+\.\s+[A-Z]|[A-H]\.\s+[A-Za-z])",
    re.IGNORECASE,
)
_MAX_FIGURE_CAPTION_LINES = 5
_SUBFIGURE_PAIR_LINE_RE = re.compile(r"^\([a-z]\).+\([a-z]\)", re.IGNORECASE)


def normalize_caption_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def parse_figure_number(caption: str | None) -> int | None:
    if not caption:
        return None
    text = normalize_caption_text(caption)
    m = _FIGURE_NUM_STRICT_RE.search(text)
    if m:
        return int(m.group(1))
    m = _FIGURE_NUM_LOOSE_RE.search(text)
    return int(m.group(1)) if m else None


def subfigure_labels(caption: str | None) -> list[str]:
    if not caption:
        return []
    text = normalize_caption_text(caption)
    return [g.lower() for g in _SUBFIGURE_LABEL_RE.findall(text)]


def figure_caption_continuation_line(line: str, fig_num: int) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False
    if figure_caption_boundary_line(stripped, fig_num):
        return False
    if _FIGURE_CAPTION_LINE_RE.match(stripped):
        return bool(re.match(rf"^fig(?:ure)?\.?\s*{fig_num}\b", stripped, re.IGNORECASE))
    if re.match(r"^\([a-z]\)", stripped, re.IGNORECASE):
        return True
    if stripped[0].islower():
        return True
    if stripped.startswith("and (") or stripped.endswith(","):
        return True
    if re.search(r"\([a-z]\)", stripped, re.IGNORECASE):
        return True
    if re.search(rf"fig\.?\s*{fig_num}\s*\([a-z]\)", stripped, re.IGNORECASE):
        return True
    if re.search(
        r"\b(?:antenna|simulated|measured|comparisons?|configuration|distribution|"
        r"efficiency|gain|radiation|photographs?|results?)\b",
        stripped,
        re.IGNORECASE,
    ):
        return True
    return False


def figure_caption_boundary_line(line: str, fig_num: int) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False
    if _SECTION_HEADING_STOP_RE.match(stripped):
        return True
    if _FIGURE_CAPTION_LINE_RE.match(stripped) and not re.match(
        rf"^fig(?:ure)?\.?\s*{fig_num}\b",
        stripped,
        re.IGNORECASE,
    ):
        return True
    return False


def find_subfigure_pair_line_near_caption(
    page_blocks: list,
    caption_bbox: list[float] | None,
    *,
    page_width: float = 612.0,
    max_below: float = 95.0,
) -> str | None:
    """Return a line like '(a) ... (b) ...' directly under a figure caption."""
    if not caption_bbox or len(caption_bbox) < 4:
        return None
    cap_y1 = float(caption_bbox[3])
    cap_center_x = (float(caption_bbox[0]) + float(caption_bbox[2])) / 2.0
    candidates: list[tuple[float, str]] = []
    for block in page_blocks:
        if getattr(block, "type", None) != "text":
            continue
        text = getattr(block, "text", None) or ""
        bbox = getattr(block, "bbox", None)
        if not text.strip() or not bbox or len(bbox) < 4:
            continue
        block_top = float(bbox[1])
        if block_top < cap_y1 - 1.0 or block_top > cap_y1 + max_below:
            continue
        block_center_x = (float(bbox[0]) + float(bbox[2])) / 2.0
        if abs(block_center_x - cap_center_x) > page_width * 0.34:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if _SUBFIGURE_PAIR_LINE_RE.match(stripped):
                candidates.append((block_top, stripped))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def join_figure_caption_lines(
    lines: list[str],
    *,
    fig_num: int,
    max_lines: int = _MAX_FIGURE_CAPTION_LINES,
) -> str:
    parts: list[str] = []
    physical = 0
    for line in lines:
        stripped = (line or "").strip()
        if not stripped:
            if parts and physical >= 1:
                break
            continue
        if parts and figure_caption_boundary_line(stripped, fig_num):
            break
        if parts and physical >= max_lines:
            break
        if parts and not figure_caption_continuation_line(stripped, fig_num):
            if not _FIGURE_CAPTION_LINE_RE.match(stripped):
                break
        if stripped not in (parts[-1] if parts else ""):
            parts.append(stripped)
        physical += 1
    return "\n".join(parts).strip()
