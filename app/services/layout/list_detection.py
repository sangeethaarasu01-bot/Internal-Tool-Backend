"""Deterministic list marker detection, sequence grouping, and continuation logic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.models.document_structure import ProcessedBlock

from app.services.layout.semantic_patterns import (
    MAX_HEADING_WORDS,
    MAX_SUBSECTION_CHARS,
    ROMAN_SECTION_RE,
    first_line,
    is_letter_subsection_heading,
    is_roman_section_heading,
    normalize_text,
)

ListType = Literal["bullet", "order"]

BULLET_CHARS = "•▪▫◦○●■□"
BULLET_MARKER_RE = re.compile(
    rf"^([{re.escape(BULLET_CHARS)}\-*–—])\s+(.+)$",
    re.UNICODE,
)

ORDERED_MARKER_PATTERNS: list[tuple[re.Pattern[str], str, ListType]] = [
    (re.compile(r"^(\d+\))\s+(.+)$"), "paren_numeric", "order"),
    (re.compile(r"^\((\d+)\)\s+(.+)$"), "paren_wrapped_numeric", "order"),
    (re.compile(r"^\[(\d+)\]\s+(.+)$"), "bracket_numeric", "order"),
    (re.compile(r"^(\d+\.)\s+(.+)$"), "dot_numeric", "order"),
    (re.compile(r"^\(([a-z])\)\s+(.+)$"), "paren_lower_alpha", "order"),
    (re.compile(r"^\(([A-Z])\)\s+(.+)$"), "paren_upper_alpha", "order"),
    (re.compile(r"^([a-z]\))\s+(.+)$"), "lower_alpha_paren", "order"),
    (re.compile(r"^([A-Z]\))\s+(.+)$"), "upper_alpha_paren", "order"),
    (re.compile(r"^([ivxlc]+)\.\s+(.+)$"), "dot_roman_lower", "order"),
    (re.compile(r"^((?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.)\s+(.+)$", re.I), "dot_roman_upper", "order"),
    (re.compile(r"^([a-z]\.)\s+(.+)$"), "dot_lower_alpha", "order"),
]

LIST_GROUP_GAP = 30.0
LIST_CONTINUATION_GAP = 38.0
LIST_INDENT_TOLERANCE = 24.0
LIST_MARKER_X_TOLERANCE = 8.0
LIST_CONTINUATION_FONT_TOLERANCE = 2.5
LIST_CONTINUATION_TYPES = frozenset({"PARAGRAPH", "BODY_TEXT", "UNKNOWN_TEXT", "EQUATION_FRAGMENT"})

_ROMAN_VALUES = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
}


@dataclass(frozen=True)
class ListMarkerInfo:
    list_type: ListType
    marker: str
    content: str
    pattern_name: str
    sequence_key: str | None = None
    sequence_index: int | None = None


def parse_list_marker(text: str, *, in_references: bool = False) -> ListMarkerInfo | None:
    """Parse a line into list marker metadata and stripped content."""
    line = first_line(text)
    if not line:
        return None

    bullet_match = BULLET_MARKER_RE.match(line)
    if bullet_match:
        marker = bullet_match.group(1)
        content = bullet_match.group(2).strip()
        if content:
            return ListMarkerInfo("bullet", marker, content, "bullet_glyph")

    for pattern, name, list_type in ORDERED_MARKER_PATTERNS:
        match = pattern.match(line)
        if not match:
            continue
        marker = match.group(1)
        content = match.group(2).strip()
        if not content:
            continue
        if name == "bracket_numeric" and in_references:
            continue
        if name == "dot_roman_upper" and is_roman_section_heading(text):
            continue
        if name == "dot_numeric" and is_likely_heading_not_list(text):
            continue
        seq_key, seq_idx = _sequence_identity(name, marker)
        return ListMarkerInfo(list_type, marker, content, name, seq_key, seq_idx)

    return None


def is_list_item(text: str, *, in_references: bool = False) -> bool:
    return parse_list_marker(text, in_references=in_references) is not None


def is_likely_heading_not_list(
    text: str,
    block: ProcessedBlock | None = None,
    *,
    in_body: bool = False,
) -> bool:
    """Return True when a numbered/letter prefix is more likely a heading than a list item."""
    line = first_line(text)
    if is_roman_section_heading(text):
        return True
    if is_letter_subsection_heading(text, block):
        return True

    dot_numeric = re.match(r"^(\d+\.)\s+(.+)$", line)
    if dot_numeric:
        content = dot_numeric.group(2)
        words = content.split()
        if len(words) <= MAX_HEADING_WORDS and content.isupper():
            return True
        if len(words) <= 4 and not re.search(r"[:;,]", content):
            upper_ratio = sum(1 for w in words if w.isupper()) / max(len(words), 1)
            if upper_ratio >= 0.75:
                return True

    upper_alpha_dot = re.match(r"^([A-Z]\.)\s+(.+)$", line)
    if upper_alpha_dot and in_body:
        content = upper_alpha_dot.group(2)
        words = content.split()
        if len(line) <= MAX_SUBSECTION_CHARS and len(words) <= MAX_HEADING_WORDS:
            if block is not None and (block.is_bold or (block.dominant_font_size or 0) >= 10):
                return True
            if re.match(r"^[A-Z][a-z]", content):
                return True

    roman_dot = re.match(r"^([IVXLC]+\.)\s+(.+)$", line)
    if roman_dot and ROMAN_SECTION_RE.match(line):
        return True

    return False


def markers_form_sequence(prev: ListMarkerInfo, curr: ListMarkerInfo) -> bool:
    if prev.list_type != curr.list_type:
        return False
    if prev.list_type == "bullet":
        return prev.pattern_name == curr.pattern_name
    if prev.sequence_key is None or curr.sequence_key is None:
        return prev.pattern_name == curr.pattern_name
    if prev.sequence_key != curr.sequence_key:
        return False
    if prev.sequence_index is None or curr.sequence_index is None:
        return False
    return curr.sequence_index == prev.sequence_index + 1


def is_semantic_list_boundary(block: ProcessedBlock) -> bool:
    """True when a block should never be absorbed as list-item continuation."""
    text = normalize_text(block.text)
    line = first_line(block.text)
    if not text:
        return True
    if parse_list_marker(block.text) is not None:
        return True
    if is_likely_heading_not_list(block.text, block, in_body=True):
        return True
    if is_roman_section_heading(block.text) or is_letter_subsection_heading(block.text, block):
        return True
    if re.match(r"^(?:where|fig\.|table\s+|references?$)", line, re.I):
        return True
    return False


def is_layout_continuation(prev: ProcessedBlock, block: ProcessedBlock) -> bool:
    """Layout-based wrap continuation compatible with paragraph merge heuristics."""
    if prev.column != block.column:
        if block.page_number != prev.page_number + 1:
            return False
        if prev.column != block.column:
            return False

    gap = _vertical_gap(prev, block)
    if prev.page_number == block.page_number and gap > LIST_CONTINUATION_GAP:
        return False

    anchor_x = prev.bbox[0]
    block_x = block.bbox[0]
    if block_x + LIST_INDENT_TOLERANCE < anchor_x - 6.0:
        return False

    prev_size = prev.dominant_font_size or 10.0
    cur_size = block.dominant_font_size or 10.0
    if abs(prev_size - cur_size) > LIST_CONTINUATION_FONT_TOLERANCE:
        return False

    return True


def is_list_continuation(
    block: ProcessedBlock,
    item_blocks: list[ProcessedBlock],
    marker_info: ListMarkerInfo | None,
) -> bool:
    """True when a non-marker block continues the current list item."""
    if not item_blocks:
        return False
    if is_semantic_list_boundary(block):
        return False
    previous_line = _last_content_line(item_blocks[-1].text)
    current_line = first_line(block.text)
    if is_independent_paragraph_start(previous_line, current_line):
        return False
    return is_layout_continuation(item_blocks[-1], block)


def is_list_item_body_continuation(
    block: ProcessedBlock,
    item_blocks: list[ProcessedBlock],
    marker_info: ListMarkerInfo | None,
    sem_type: str,
) -> bool:
    if not item_blocks or not marker_info:
        return False
    if sem_type not in LIST_CONTINUATION_TYPES:
        return False
    if sem_type == "EQUATION_FRAGMENT":
        return (
            not is_semantic_list_boundary(block)
            and is_layout_continuation(item_blocks[-1], block)
        )
    return is_list_continuation(block, item_blocks, marker_info)


def join_text_parts(parts: list[str]) -> str:
    """Join extracted blocks without losing words across line wraps."""
    merged = ""
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        if not merged:
            merged = cleaned
            continue
        if merged.endswith("-"):
            merged = merged[:-1] + cleaned
        elif merged[-1] in ".:;?!":
            merged = f"{merged} {cleaned}"
        else:
            merged = f"{merged} {cleaned}"
    return merged.strip()


def merge_list_item_text(blocks: list[ProcessedBlock], marker_info: ListMarkerInfo) -> str:
    """Merge all source blocks for one list item, preserving full extracted wording."""
    if not blocks:
        return ""

    parts: list[str] = []
    for index, block in enumerate(blocks):
        raw = block.text or ""
        if index == 0 and parse_list_marker(raw) is not None:
            parts.append(strip_marker_from_text(raw, marker_info))
        else:
            parts.append(raw)
    return join_text_parts(normalize_text(part) for part in parts if normalize_text(part))


def union_bbox(blocks: list[ProcessedBlock]) -> list[float] | None:
    if not blocks:
        return None
    return [
        min(block.bbox[0] for block in blocks),
        min(block.bbox[1] for block in blocks),
        max(block.bbox[2] for block in blocks),
        max(block.bbox[3] for block in blocks),
    ]


def _last_content_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").split("\n") if line.strip()]
    return lines[-1] if lines else normalize_text(text)


def is_independent_paragraph_start(prev_line: str, line: str) -> bool:
    """True when a line begins a new paragraph rather than wrapping the previous one."""
    prev = prev_line.rstrip()
    cur = line.strip()
    if not cur:
        return False
    if parse_list_marker(cur) is not None:
        return True
    if prev.endswith("-"):
        return False
    if prev and prev[-1] not in ".?!:;":
        return False
    if cur[0].islower():
        return False
    if prev.endswith(".") and cur[0].isupper():
        return True
    return False


def _trim_segment_body_lines(first_content: str, rest_lines: list[str]) -> list[str]:
    kept: list[str] = []
    previous = first_content
    for line in rest_lines:
        if is_independent_paragraph_start(previous, line):
            break
        kept.append(line)
        previous = line
    return kept


def strip_marker_from_text(text: str, marker_info: ListMarkerInfo) -> str:
    line = first_line(text)
    if marker_info.pattern_name == "bullet_glyph":
        match = BULLET_MARKER_RE.match(line)
        if match:
            remainder = text.split("\n", 1)
            first = match.group(2).strip()
            if len(remainder) > 1:
                return f"{first}\n{remainder[1]}"
            return first
    for pattern, name, _ in ORDERED_MARKER_PATTERNS:
        if name != marker_info.pattern_name:
            continue
        match = pattern.match(line)
        if match:
            remainder = text.split("\n", 1)
            first = match.group(2).strip()
            if len(remainder) > 1:
                return f"{first}\n{remainder[1]}"
            return first
    return normalize_text(text)


def extract_list_segments_from_block(
    text: str,
    *,
    in_references: bool = False,
) -> tuple[list[tuple[ListMarkerInfo, str]], str | None]:
    """Split one extracted block that contains multiple line-start list markers."""
    lines = (text or "").split("\n")
    line_markers: list[tuple[int, ListMarkerInfo]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        marker = parse_list_marker(stripped, in_references=in_references)
        if marker and not is_likely_heading_not_list(stripped):
            line_markers.append((index, marker))

    if len(line_markers) < 2:
        return [], None

    segments: list[tuple[ListMarkerInfo, str]] = []
    remainder_lines: list[str] = []
    for idx, (line_index, marker) in enumerate(line_markers):
        end_line = line_markers[idx + 1][0] if idx + 1 < len(line_markers) else len(lines)
        chunk_lines = [line.strip() for line in lines[line_index:end_line] if line.strip()]
        if not chunk_lines:
            continue
        first_line_text = chunk_lines[0]
        first_marker = parse_list_marker(first_line_text, in_references=in_references) or marker
        first_content = strip_marker_from_text(first_line_text, first_marker)
        rest = chunk_lines[1:]
        kept_rest = _trim_segment_body_lines(first_content, rest)
        if idx == len(line_markers) - 1 and len(kept_rest) < len(rest):
            remainder_lines.extend(rest[len(kept_rest) :])
        content = join_text_parts([first_content, *kept_rest])
        if content:
            segments.append((marker, content))

    remainder = join_text_parts(remainder_lines) if remainder_lines else None
    return segments, remainder


def _line_start_markers(
    text: str,
    *,
    in_references: bool = False,
) -> list[tuple[int, ListMarkerInfo]]:
    lines = (text or "").split("\n")
    markers: list[tuple[int, ListMarkerInfo]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        marker = parse_list_marker(stripped, in_references=in_references)
        if marker and not is_likely_heading_not_list(stripped):
            markers.append((index, marker))
    return markers


def expand_multi_marker_list_blocks(
    enriched: list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]],
    *,
    in_references: bool = False,
) -> list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]]:
    """Expand blocks that contain multiple inline list markers into consecutive LIST_ITEM blocks."""
    expanded: list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]] = []
    for block, sem_type, confidence, reason, marker_info in enriched:
        if sem_type in {"FIGURE_CAPTION", "TABLE_CAPTION", "REFERENCE", "SECTION", "SUBSECTION"}:
            expanded.append((block, sem_type, confidence, reason, marker_info))
            continue
        segments, remainder = extract_list_segments_from_block(block.text, in_references=in_references)
        if len(segments) <= 1:
            first_marker = parse_list_marker(block.text, in_references=in_references)
            expanded.append(
                (
                    block,
                    sem_type,
                    confidence,
                    reason,
                    marker_info or first_marker,
                )
            )
            continue

        line_markers = _line_start_markers(block.text, in_references=in_references)
        if line_markers:
            first_marker_line = line_markers[0][0]
            lines = (block.text or "").split("\n")
            pre_list_lines = [line.strip() for line in lines[:first_marker_line] if line.strip()]
            pre_list_text = join_text_parts(pre_list_lines)
            if pre_list_text:
                expanded.append(
                    (
                        block.model_copy(update={"text": pre_list_text}),
                        "PARAGRAPH",
                        confidence,
                        "pre_list_paragraph",
                        None,
                    )
                )

        for index, (marker, content) in enumerate(segments):
            synthetic = block.model_copy(update={"text": content})
            expanded.append((synthetic, "LIST_ITEM", max(confidence, 0.86), reason, marker))
        if remainder:
            remainder_block = block.model_copy(update={"text": remainder})
            expanded.append((remainder_block, "PARAGRAPH", confidence, "post_list_paragraph", None))
    return expanded


def reclassify_list_sequences(
    typed: list[tuple[ProcessedBlock, str, float, str | None]],
    *,
    in_references: bool = False,
) -> list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]]:
    """Detect ordered/bullet sequences and upgrade matching blocks to LIST_ITEM."""
    enriched: list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]] = [
        (block, sem_type, conf, reason, None) for block, sem_type, conf, reason in typed
    ]

    i = 0
    while i < len(enriched):
        block, sem_type, conf, reason, _ = enriched[i]
        if sem_type in {"FIGURE_CAPTION", "TABLE_CAPTION", "REFERENCE"}:
            i += 1
            continue
        marker = parse_list_marker(block.text, in_references=in_references)
        if marker is None or is_likely_heading_not_list(block.text, block, in_body=True):
            i += 1
            continue
        if sem_type in {"SECTION", "SUBSECTION"} and is_likely_heading_not_list(block.text, block, in_body=True):
            i += 1
            continue

        group_indices = [i]
        group_markers = [marker]
        j = i + 1
        while j < len(enriched):
            nxt_block, nxt_type, _, _, _ = enriched[j]
            nxt_marker = parse_list_marker(nxt_block.text, in_references=in_references)
            if nxt_marker is None:
                break
            if is_likely_heading_not_list(nxt_block.text, nxt_block, in_body=True):
                break
            prev_block = enriched[group_indices[-1]][0]
            if _vertical_gap(prev_block, nxt_block) > LIST_GROUP_GAP:
                break
            if prev_block.column != nxt_block.column:
                break
            if not markers_form_sequence(group_markers[-1], nxt_marker):
                if marker.list_type == "bullet" and nxt_marker.list_type == "bullet":
                    if abs(nxt_block.bbox[0] - prev_block.bbox[0]) > LIST_MARKER_X_TOLERANCE:
                        break
                else:
                    break
            group_indices.append(j)
            group_markers.append(nxt_marker)
            j += 1

        if len(group_indices) >= 2 or _single_item_list_confidence(block, marker) >= 0.7:
            for idx, marker_info in zip(group_indices, group_markers):
                b, _, c, r, _ = enriched[idx]
                enriched[idx] = (b, "LIST_ITEM", max(c, 0.84), r, marker_info)
        i += 1

    for idx, (block, sem_type, conf, reason, marker_info) in enumerate(enriched):
        if sem_type != "LIST_ITEM" and marker_info is None:
            marker = parse_list_marker(block.text, in_references=in_references)
            if marker and not is_likely_heading_not_list(block.text, block, in_body=True):
                if _single_item_list_confidence(block, marker) >= 0.8:
                    enriched[idx] = (block, "LIST_ITEM", max(conf, 0.84), reason, marker)

    return enriched


def collect_list_items(
    enriched: list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]],
    start: int,
) -> tuple[list[tuple[ListMarkerInfo, list[ProcessedBlock], float, str]], int]:
    """Collect one list run starting at index start. Returns items and next index."""
    items: list[tuple[ListMarkerInfo, list[ProcessedBlock], float, str]] = []
    i = start
    current_blocks: list[ProcessedBlock] = []
    current_marker: ListMarkerInfo | None = None
    current_conf = 0.84
    current_reason = "ordered_marker"

    while i < len(enriched):
        block, sem_type, conf, _, marker_info = enriched[i]
        if sem_type == "LIST_ITEM":
            if current_blocks and current_marker is not None:
                items.append((current_marker, current_blocks, current_conf, current_reason))
                current_blocks = []
            parsed = marker_info or parse_list_marker(block.text)
            if parsed is None:
                break
            if items and not markers_form_sequence(items[-1][0], parsed):
                if not (parsed.list_type == "bullet" and items[-1][0].list_type == "bullet"):
                    break
                prev_block = items[-1][1][-1]
                if _vertical_gap(prev_block, block) > LIST_GROUP_GAP:
                    break
            current_marker = parsed
            current_blocks = [block]
            current_conf = conf
            current_reason = f"{parsed.pattern_name}+sequence"
            i += 1
            continue

        if current_blocks and current_marker is not None and is_list_item_body_continuation(
            block,
            current_blocks,
            current_marker,
            sem_type,
        ):
            current_blocks.append(block)
            if len(current_blocks) > 1:
                current_reason = f"{current_marker.pattern_name}+sequence+continuation_blocks"
                current_conf = min(0.98, max(current_conf, conf) + 0.02)
            i += 1
            continue
        break

    if current_blocks and current_marker is not None:
        items.append((current_marker, current_blocks, current_conf, current_reason))

    return items, i


def _single_item_list_confidence(block: ProcessedBlock, marker: ListMarkerInfo) -> float:
    content = marker.content
    score = 0.55
    if marker.pattern_name in {"paren_numeric", "paren_wrapped_numeric", "lower_alpha_paren", "paren_lower_alpha"}:
        score += 0.2
    if ":" in content:
        score += 0.15
    if len(content) > 40:
        score += 0.1
    if re.search(r"\(\w+\)|=\s*|\bmodel\b", content, re.I):
        score += 0.05
    if marker.pattern_name in {"paren_lower_alpha", "paren_upper_alpha", "lower_alpha_paren"}:
        if len(content.split()) <= 10 and not re.search(r":", content):
            score -= 0.25
    if is_likely_heading_not_list(block.text, block, in_body=True):
        score -= 0.5
    return min(max(score, 0.0), 0.98)


def _sequence_identity(pattern_name: str, marker: str) -> tuple[str | None, int | None]:
    if pattern_name in {"paren_numeric", "paren_wrapped_numeric", "bracket_numeric", "dot_numeric"}:
        digits = re.search(r"\d+", marker)
        return ("numeric", int(digits.group(0)) if digits else None)
    if pattern_name in {"paren_lower_alpha", "lower_alpha_paren", "dot_lower_alpha"}:
        letter = re.search(r"[a-z]", marker, re.I)
        if not letter:
            return (pattern_name, None)
        return ("alpha_lower", ord(letter.group(0).lower()) - ord("a") + 1)
    if pattern_name in {"paren_upper_alpha", "upper_alpha_paren"}:
        letter = re.search(r"[A-Z]", marker)
        if not letter:
            return (pattern_name, None)
        return ("alpha_upper", ord(letter.group(0)) - ord("A") + 1)
    if pattern_name == "dot_roman_lower":
        value = _ROMAN_VALUES.get(marker.rstrip(".").lower())
        return ("roman_lower", value)
    if pattern_name == "dot_roman_upper":
        value = _ROMAN_VALUES.get(marker.rstrip(".").lower())
        return ("roman_upper", value)
    return (pattern_name, None)


def _vertical_gap(prev: ProcessedBlock, current: ProcessedBlock) -> float:
    if prev.page_number != current.page_number:
        return 0.0
    return current.bbox[1] - prev.bbox[3]


def _estimated_marker_width(marker: str) -> float:
    return max(12.0, len(marker) * 4.5)
