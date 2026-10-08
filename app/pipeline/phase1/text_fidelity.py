"""Forensic analysis of PDF text fidelity vs XML-safe normalization (Phase 1)."""

from __future__ import annotations

from collections import Counter

from app.models.extraction import ExtractionResult
from app.models.extracted_document import InvalidCharacterPageSummary, InvalidCharacterReport
from app.services.layout.reading_order import order_document_blocks
from app.utils.xml_text import find_invalid_xml_char_codes, strip_illegal_xml_chars

# Human-readable origin hint for debug reports (not a substitute for per-glyph analysis).
_ORIGIN_HINT = (
    "Control characters appear in PyMuPDF get_text('dict') output before Phase 1 XML "
    "sanitization. They are common near mathematical notation when PDF fonts/CMaps map "
    "glyphs to C0 control code points; they are not introduced by the legacy XML generator."
)

_WARNING_SOURCE = (
    "Log line 'Invalid XML character(s) removed' is emitted by "
    "app.utils.xml_text.sanitize_xml_text (via escape_xml_text) when building "
    "structure.semantic.tagged_output in app.services.layout.semantic_renderer."
)


def join_ordered_block_text(raw: ExtractionResult, *, page_number: int | None = None) -> str:
    """Concatenate block text in reading order (unsanitized PyMuPDF extract)."""
    parts: list[str] = []
    for block, pn in order_document_blocks(raw.pages):
        if page_number is not None and pn != page_number:
            continue
        text = block.text or ""
        if text:
            parts.append(text)
    return "\n".join(parts)


def _count_invalid_chars(text: str) -> tuple[Counter[int], int]:
    illegal = set(find_invalid_xml_char_codes(text))
    counts: Counter[int] = Counter()
    for char in text:
        code = ord(char)
        if code in illegal:
            counts[code] += 1
    return counts, sum(counts.values())


def scan_text_fidelity(
    raw: ExtractionResult,
    *,
    normalized_text: str | None = None,
) -> InvalidCharacterReport:
    """Scan raw PyMuPDF-ordered text for XML-illegal control characters."""
    raw_text = join_ordered_block_text(raw)
    norm = normalized_text if normalized_text is not None else strip_illegal_xml_chars(raw_text)

    total_counts, total_removed = _count_invalid_chars(raw_text)
    code_points = sorted(total_counts.keys())
    occurrences_by_code = {f"U+{code:04X}": total_counts[code] for code in code_points}

    page_summaries: list[InvalidCharacterPageSummary] = []
    for page in raw.pages:
        page_text = join_ordered_block_text(raw, page_number=page.page_number)
        page_counts, page_removed = _count_invalid_chars(page_text)
        if not page_removed:
            continue
        page_summaries.append(
            InvalidCharacterPageSummary(
                page_number=page.page_number,
                invalid_character_count=page_removed,
                code_points=sorted(page_counts.keys()),
                occurrences_by_code={f"U+{code:04X}": page_counts[code] for code in page_counts},
            )
        )

    chars_removed = len(raw_text) - len(norm)
    if chars_removed < 0:
        chars_removed = total_removed

    warnings: list[str] = []
    if total_removed:
        warnings.append(_ORIGIN_HINT)
        warnings.append(_WARNING_SOURCE)
        warnings.append(
            f"Detected {total_removed} XML-illegal control character occurrence(s) "
            f"across {len(page_summaries)} page(s); {chars_removed} character(s) would be "
            "stripped for XML intermediate output (raw extract preserved separately)."
        )

    return InvalidCharacterReport(
        invalid_character_occurrences=total_removed,
        distinct_code_points=code_points,
        occurrences_by_code=occurrences_by_code,
        characters_removed_for_xml=chars_removed,
        affected_pages=page_summaries,
        raw_character_count=len(raw_text),
        normalized_character_count=len(norm),
        origin_hint=_ORIGIN_HINT,
        xml_sanitization_warning_source=_WARNING_SOURCE,
        warnings=warnings,
    )
