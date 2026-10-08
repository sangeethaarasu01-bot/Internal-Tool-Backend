"""Equation region preservation for Phase 1 (no LaTeX/XML conversion)."""

from __future__ import annotations

import re

from app.models.document_structure import ProcessedBlock
from app.models.extracted_document import EquationExtractionQuality, ExtractedEquation
from app.utils.math_latex import is_plausible_display_equation, split_equation_label
from app.utils.xml_text import find_invalid_xml_char_codes

_AQ_LINE_RE = re.compile(r"^AQ:\s*\d+", re.IGNORECASE)
_AUTHOR_QUERY_RE = re.compile(r"author\s+please\s+answer|author\s+queries", re.IGNORECASE)
_NUMBERED_LABEL_RE = re.compile(r"^\(\d+\)$")
_STANDALONE_NUMBER_LABEL_RE = re.compile(r"^\(\d+\)\s*$")
_PROSE_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
        "of", "on", "or", "our", "that", "the", "this", "to", "was", "were", "with",
        "according", "however", "noting", "based",
    }
)
_INLINE_EQ_CITATION_RE = re.compile(
    r"^(?:based\s+on|according\s+to|see|from)\s+\(\d+\)",
    re.IGNORECASE,
)
_PROSE_EQUATION_LEAD_RE = re.compile(
    r"^(?:similarly|it can be seen|where the|as follows|can be derived)",
    re.IGNORECASE,
)
_INLINE_MATH_RE = re.compile(
    r"(?:\$[^$]+\$|[A-Za-z][_{^][A-Za-z0-9]|\\(?:alpha|beta|gamma|theta|omega|mu|phi))"
)
_MATH_BODY_RE = re.compile(
    r"(=|≈|∑|∫|±|≤|≥|√|\^|_\{|[A-Za-z]_[A-Za-z0-9]|[A-Za-z]\^\d)",
)


def _is_prose_heavy(text: str) -> bool:
    words = re.findall(r"[A-Za-z]+", text.lower())
    if len(words) < 6:
        return False
    prose_hits = sum(1 for word in words if word in _PROSE_WORDS)
    return prose_hits / len(words) > 0.5


def _has_numeric_equation_label(text: str) -> tuple[str | None, str]:
    label, body = split_equation_label(text)
    if label and _NUMBERED_LABEL_RE.match(label.strip()):
        return label, body
    return None, text


def _is_front_matter_block(block: ProcessedBlock, text: str) -> bool:
    if block.page_number > 2:
        return False
    normalized = (text or "").strip()
    if _AQ_LINE_RE.match(normalized) or _AUTHOR_QUERY_RE.search(normalized):
        return True
    return False


def _body_has_math_content(body: str) -> bool:
    stripped = (body or "").strip()
    if not stripped or stripped in {".", ",", ";"}:
        return True
    if is_plausible_display_equation(stripped):
        return True
    return bool(_MATH_BODY_RE.search(stripped))


def is_numbered_display_equation(block: ProcessedBlock, text: str) -> bool:
    """True only for numbered display equations ``(N)`` (not inline prose citations)."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _is_front_matter_block(block, normalized):
        return False
    if _AQ_LINE_RE.match(normalized):
        return False
    if _INLINE_EQ_CITATION_RE.match(normalized):
        return False

    label, body = _has_numeric_equation_label(normalized)
    if label:
        body_stripped = (body or "").strip()
        if _INLINE_EQ_CITATION_RE.match(body_stripped):
            return False
        if _is_prose_heavy(body_stripped) and not re.search(r"\d", body_stripped):
            return False
        if _body_has_math_content(body_stripped):
            return True
        return bool(re.search(r"\d", body_stripped) and len(body_stripped) < 240)

    if block.classification != "EQUATION":
        return False
    if _is_prose_heavy(normalized):
        return False
    return is_plausible_display_equation(normalized) and "=" in normalized


def _coalesce_equation_texts(processed: list[ProcessedBlock]) -> list[tuple[ProcessedBlock, str]]:
    """Attach orphan ``(N)`` labels to adjacent equation blocks in reading order."""
    ordered = [
        block
        for block in sorted(processed, key=lambda block: block.reading_order_index)
        if not block.exclude_from_content and (block.text or "").strip()
    ]
    merged: list[tuple[ProcessedBlock, str]] = []
    index = 0
    while index < len(ordered):
        block = ordered[index]
        text = (block.text or "").strip()
        if _STANDALONE_NUMBER_LABEL_RE.match(text):
            if merged and _has_numeric_equation_label(merged[-1][1])[0] is None:
                prev_block, prev_text = merged[-1]
                if len(prev_text) < 120 and _is_math_fragment(prev_text):
                    merged[-1] = (prev_block, f"{prev_text}\n{text}")
                else:
                    merged.append((block, text))
            elif index + 1 < len(ordered):
                next_block = ordered[index + 1]
                next_text = (next_block.text or "").strip()
                if _is_math_fragment(next_text) and len(next_text) < 120:
                    merged.append((next_block, f"{next_text}\n{text}"))
                    index += 2
                    continue
                merged.append((block, text))
            else:
                merged.append((block, text))
        else:
            merged.append((block, text))
        index += 1
    return merged


def _equation_number_from_label(label: str | None) -> int | None:
    if not label:
        return None
    match = re.search(r"\d+", label)
    return int(match.group()) if match else None


def _is_trivial_equation_body(body: str) -> bool:
    stripped = re.sub(r"\s+", "", body or "")
    return not stripped or stripped in {".", ",", ";", ".\n", "."}


def _is_math_fragment(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _is_prose_heavy(normalized):
        return False
    if len(normalized) > 96:
        return False
    if "=" in normalized:
        return True
    if _MATH_BODY_RE.search(normalized):
        return True
    if re.search(r"[Zz]\s*\d+\s*=", normalized):
        return True
    if re.search(r"M[_a-zA-Z]*,?\s*ON", normalized):
        return True
    if re.search(r"sL[_a-zA-Z]*|rON|Madj", normalized):
        return True
    if re.fullmatch(r"[A-Za-z]{1,4}", normalized):
        return True
    return False


def _collect_spatial_math_fragments(
    processed: list[ProcessedBlock],
    block: ProcessedBlock,
    equation_number: int | None,
) -> list[tuple[float, float, str, str]]:
    if not block.bbox or len(block.bbox) < 4:
        return []
    band_top = block.bbox[1] - 28.0
    band_bottom = block.bbox[3] + 18.0
    label_right = block.bbox[2] + 4.0
    fragments: list[tuple[float, float, str, str]] = []
    for candidate in processed:
        if candidate.exclude_from_content or candidate.page_number != block.page_number:
            continue
        if candidate.block_id == block.block_id:
            continue
        if not candidate.bbox or len(candidate.bbox) < 4:
            continue
        center_y = (candidate.bbox[1] + candidate.bbox[3]) / 2.0
        if center_y < band_top or center_y > band_bottom:
            continue
        if candidate.bbox[0] > label_right:
            continue
        candidate_text = (candidate.text or "").strip()
        if not candidate_text or _STANDALONE_NUMBER_LABEL_RE.match(candidate_text):
            continue
        if _is_trivial_equation_body(candidate_text):
            continue
        if _is_prose_heavy(candidate_text):
            continue
        if _PROSE_EQUATION_LEAD_RE.search(candidate_text):
            continue
        if equation_number is not None:
            label_hits = [int(match) for match in re.findall(r"\((\d+)\)", candidate_text)]
            if label_hits and any(number != equation_number for number in label_hits):
                continue
        if re.search(r"\(\d+\)", candidate_text) and len(candidate_text) > 64:
            continue
        if not _is_math_fragment(candidate_text):
            continue
        fragments.append(
            (candidate.bbox[1], candidate.bbox[0], candidate_text, candidate.block_id)
        )
    fragments.sort(key=lambda item: (item[1], item[0]))
    return fragments


def _repair_equation_text_from_neighbors(
    processed: list[ProcessedBlock],
    block: ProcessedBlock,
    text: str,
) -> tuple[str, list[str]]:
    """Pull split display-math fragments onto the same horizontal band as ``(N)``."""
    label, body = split_equation_label(text)
    if not label or not _is_trivial_equation_body(body):
        return text, [block.block_id]
    if not block.bbox or len(block.bbox) < 4:
        return text, [block.block_id]

    fragments = _collect_spatial_math_fragments(
        processed,
        block,
        _equation_number_from_label(label),
    )
    if not fragments:
        return text, [block.block_id]

    parts = [part_text for _y, _x, part_text, _bid in fragments]
    source_ids = [bid for _y, _x, _part, bid in fragments] + [block.block_id]
    merged_body = " ".join(parts)
    return f"{merged_body}\n{label}", source_ids


def count_inline_math_occurrences(processed: list[ProcessedBlock]) -> int:
    """Count inline math symbols in body text (not numbered display equations)."""
    count = 0
    for block, text in _coalesce_equation_texts(processed):
        if is_numbered_display_equation(block, text):
            continue
        if is_plausible_display_equation(text) and "=" in text and len(text) < 120:
            count += 1
            continue
        count += len(_INLINE_MATH_RE.findall(text))
    return count


def extract_equations(processed: list[ProcessedBlock]) -> list[ExtractedEquation]:
    equations: list[ExtractedEquation] = []
    seen_numbers: set[int] = set()
    index = 0
    for block, text in _coalesce_equation_texts(processed):
        if not is_numbered_display_equation(block, text):
            continue
        label, _body = split_equation_label(text)
        eq_number = _equation_number_from_label(label)
        if eq_number is not None:
            if eq_number in seen_numbers:
                continue
            seen_numbers.add(eq_number)
        index += 1
        raw_text, source_ids = _repair_equation_text_from_neighbors(processed, block, text)
        label, _body = split_equation_label(raw_text)
        invalid = find_invalid_xml_char_codes(raw_text)
        is_eq = block.classification == "EQUATION"
        equations.append(
            ExtractedEquation(
                equation_id=f"eq_{index}",
                page_number=block.page_number,
                raw_text=raw_text,
                bbox=list(block.bbox) if block.bbox else None,
                label=label,
                source_block_ids=source_ids,
                extraction_quality=EquationExtractionQuality(
                    confidence=block.confidence if is_eq else 0.55,
                    label_detected=bool(label),
                    contains_control_chars=bool(invalid),
                ),
            )
        )
    return equations
