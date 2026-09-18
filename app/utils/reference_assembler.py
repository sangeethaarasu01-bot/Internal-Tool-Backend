"""Assemble numbered bibliography entries from PDF reference-section blocks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.models.document_structure import ProcessedBlock
from app.models.ir_schema import IRNode
from app.services.ir_builder import build_ir_node
from app.services.layout.semantic_patterns import (
    REFERENCE_HEADING_RE,
    first_line,
    looks_like_reference_entry,
    normalize_text,
)

logger = logging.getLogger(__name__)

REFERENCE_LABEL_NUMBER_RE = re.compile(r"^\[(\d+)\]")
STANDALONE_REFERENCE_LABEL_RE = re.compile(r"^\[\d+\]$")
_REFERENCE_LABEL_AT_START_RE = re.compile(r"^(\[\d+\])\s*(.*)$", re.DOTALL)
_AUTHOR_BIOGRAPHIES_HEADING_RE = re.compile(r"^author(?:\s+biograph|\s+information)", re.IGNORECASE)
_EXCLUDED_REFERENCE_CLASSIFICATIONS = frozenset({"FOOTER", "RUNNING_HEADER", "PAGE_NUMBER"})


class ReferenceParsingError(ValueError):
    """Raised when extracted references are missing, duplicated, or out of order."""


@dataclass(frozen=True)
class AssembledReference:
    reference_number: int
    label: str
    raw_text: str
    source_block_ids: list[str]
    page_numbers: list[int]
    bbox: list[float] | None
    confidence: float

    @property
    def xml_id(self) -> str:
        return f"ref{self.reference_number}"


def parse_reference_number(label_or_text: str | None) -> int | None:
    """Extract the PDF bibliography number from ``[N]`` at the start of a label or text."""
    if not label_or_text:
        return None
    normalized = normalize_text(label_or_text)
    match = REFERENCE_LABEL_NUMBER_RE.match(normalized)
    return int(match.group(1)) if match else None


_MIN_COLUMN_GAP = 24.0
_FULL_WIDTH_GUTTER = 18.0


def _page_width_for_blocks(blocks: list[ProcessedBlock]) -> float:
    if not blocks:
        return 612.0
    return max(block.bbox[2] for block in blocks) + 12.0


def _compute_page_column_splits(blocks: list[ProcessedBlock]) -> dict[int, float]:
    """Infer the left/right column boundary per page from reference block geometry."""
    by_page: dict[int, list[ProcessedBlock]] = {}
    for block in blocks:
        by_page.setdefault(block.page_number, []).append(block)

    splits: dict[int, float] = {}
    for page_number, page_blocks in by_page.items():
        page_width = _page_width_for_blocks(page_blocks)
        default_split = page_width / 2.0
        x0_values = sorted(block.bbox[0] for block in page_blocks)
        if len(x0_values) < 2:
            splits[page_number] = default_split
            continue

        best_gap = 0.0
        split_at = default_split
        for left_x0, right_x0 in zip(x0_values, x0_values[1:]):
            gap = right_x0 - left_x0
            if gap > best_gap:
                best_gap = gap
                split_at = (left_x0 + right_x0) / 2.0

        if best_gap < _MIN_COLUMN_GAP:
            splits[page_number] = default_split
        else:
            splits[page_number] = split_at
    return splits


def _reference_layout_ranks(
    block: ProcessedBlock,
    page_splits: dict[int, float],
) -> tuple[int, int]:
    """Return ``(band, column_rank)`` for bibliography reading order."""
    x0, _y0, x1, _y1 = block.bbox
    page_split = page_splits.get(block.page_number, _page_width_for_blocks([block]) / 2.0)
    if x0 < page_split - _FULL_WIDTH_GUTTER and x1 > page_split + _FULL_WIDTH_GUTTER:
        return 0, 0

    center_x = (x0 + x1) / 2.0
    column_rank = 1 if center_x >= page_split else 0
    return 1, column_rank


def reference_block_sort_key(
    block: ProcessedBlock,
    *,
    page_splits: dict[int, float] | None = None,
) -> tuple[int, int, int, float, float]:
    """Column-major bibliography order: page, full-width band, left then right, top-to-bottom."""
    splits = page_splits or {block.page_number: _page_width_for_blocks([block]) / 2.0}
    band, column_rank = _reference_layout_ranks(block, splits)
    return (block.page_number, band, column_rank, block.bbox[1], block.bbox[0])


def sort_reference_section_blocks(blocks: list[ProcessedBlock]) -> list[ProcessedBlock]:
    """Sort bibliography blocks in human reading order for multi-column layouts."""
    page_splits = _compute_page_column_splits(blocks)
    return sorted(
        blocks,
        key=lambda block: reference_block_sort_key(block, page_splits=page_splits),
    )


def log_reference_diagnostics(
    assembled: list[AssembledReference],
    *,
    section_start_page: int | None = None,
    section_end_page: int | None = None,
) -> None:
    numbers = [ref.reference_number for ref in assembled]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    missing = (
        [number for number in range(1, max(numbers) + 1) if number not in numbers]
        if numbers
        else []
    )

    if section_start_page is not None and section_end_page is not None:
        logger.info(
            "REFERENCE SECTION pages: %s-%s",
            section_start_page,
            section_end_page,
        )
    logger.info("REFERENCE COUNT: %s", len(assembled))
    logger.info("REFERENCE ORDER BEFORE VALIDATION: %s", numbers)
    logger.info("DUPLICATE REFERENCE NUMBERS: %s", duplicates)
    logger.info("MISSING REFERENCE NUMBERS: %s", missing[:50])
    if len(missing) > 50:
        logger.info("MISSING REFERENCE NUMBERS (continued): ... %s total missing", len(missing))

    for ref in assembled:
        page = ref.page_numbers[0] if ref.page_numbers else None
        logger.info(
            "REFERENCE DETECTED | number=%s | page=%s | bbox=%s | preview=%r",
            ref.reference_number,
            page,
            ref.bbox,
            ref.raw_text[:120],
        )


def validate_reference_sequence(references: list[AssembledReference]) -> None:
    """Ensure references are contiguous ``1..N`` in layout reading order without duplicates."""
    if not references:
        return

    log_reference_diagnostics(references)

    numbers = [ref.reference_number for ref in references]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    if duplicates:
        raise ReferenceParsingError(f"Duplicate reference numbers: {duplicates}")

    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        missing = [number for number in range(1, max(numbers) + 1) if number not in numbers]
        raise ReferenceParsingError(
            "Reference order mismatch. "
            f"Expected 1..{len(numbers)}, got {numbers[:15]}{'...' if len(numbers) > 15 else ''}. "
            f"Missing: {missing[:20]}{'...' if len(missing) > 20 else ''}"
        )

    for ref in references:
        if ref.xml_id != f"ref{ref.reference_number}":
            raise ReferenceParsingError(
                f"XML id mismatch for reference {ref.reference_number}: {ref.xml_id}"
            )
        if ref.label != f"[{ref.reference_number}]":
            raise ReferenceParsingError(
                f"Label mismatch for reference {ref.reference_number}: {ref.label}"
            )


def _union_bbox(blocks: list[ProcessedBlock]) -> list[float] | None:
    if not blocks:
        return None
    return [
        min(block.bbox[0] for block in blocks),
        min(block.bbox[1] for block in blocks),
        max(block.bbox[2] for block in blocks),
        max(block.bbox[3] for block in blocks),
    ]


def _source_ids(blocks: list[ProcessedBlock]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for part in block.block_id.split(","):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                ids.append(part)
    return ids


def _is_reference_section_content_block(
    block: ProcessedBlock,
    text: str,
    *,
    is_author_bio: bool,
) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    if STANDALONE_REFERENCE_LABEL_RE.match(normalized):
        return True
    if block.exclude_from_content:
        return False
    if block.classification in _EXCLUDED_REFERENCE_CLASSIFICATIONS:
        return False
    if is_author_bio:
        return False
    return True


def _belongs_on_reference_heading_page(block: ProcessedBlock, text: str) -> bool:
    """Keep same-page bibliography blocks that appear before the REFERENCES heading."""
    normalized = normalize_text(text)
    if not normalized:
        return False
    if block.classification in _EXCLUDED_REFERENCE_CLASSIFICATIONS:
        return False
    if block.column == "FULL_WIDTH" and block.classification not in {
        "REFERENCE_TEXT",
        "PARAGRAPH",
    }:
        return False
    if block.classification in {"REFERENCE_TEXT", "PARAGRAPH"}:
        return True
    if STANDALONE_REFERENCE_LABEL_RE.match(normalized):
        return True
    if _label_at_block_start(text) is not None:
        return True
    if REFERENCE_LABEL_NUMBER_RE.search(normalized):
        return True
    return looks_like_reference_entry(text)


def collect_reference_section_blocks(
    processed: list[ProcessedBlock],
    block_sem_types: dict[str, str],
    *,
    is_author_bio,
) -> list[ProcessedBlock]:
    """Collect bibliography blocks from the REFERENCES page through author bios."""
    ordered = sorted(processed, key=lambda block: block.reading_order_index)
    heading_page: int | None = None
    for block in ordered:
        line = first_line(block.text or "")
        if REFERENCE_HEADING_RE.match(line):
            heading_page = block.page_number
            break

    if heading_page is None:
        return []

    collected: list[ProcessedBlock] = []
    for block in ordered:
        if block.page_number < heading_page:
            continue

        text = block.text or ""
        normalized = normalize_text(text)
        line = first_line(text)

        if REFERENCE_HEADING_RE.match(line):
            continue

        sem_type = block_sem_types.get(block.block_id, "")
        if sem_type == "AUTHOR":
            break
        if _AUTHOR_BIOGRAPHIES_HEADING_RE.match(line):
            break
        if is_author_bio(normalized) and collected:
            break

        if not _is_reference_section_content_block(
            block,
            text,
            is_author_bio=is_author_bio(normalized),
        ):
            continue

        if block.page_number == heading_page and not _belongs_on_reference_heading_page(
            block,
            text,
        ):
            continue

        collected.append(block)

    return sort_reference_section_blocks(collected)


def _label_at_block_start(text: str) -> tuple[int, str] | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    if STANDALONE_REFERENCE_LABEL_RE.match(normalized):
        return int(normalized[1:-1]), ""
    match = _REFERENCE_LABEL_AT_START_RE.match(normalized)
    if match:
        number = int(match.group(1)[1:-1])
        return number, match.group(2).strip()
    return None


def _iter_block_reference_segments(text: str) -> list[tuple[int | None, str]]:
    """Split a bibliography block into continuation text and ``[N]``-anchored segments."""
    normalized = normalize_text(text)
    if not normalized:
        return []

    if not re.search(r"\[\d+\]", normalized):
        return [(None, normalized)]

    parts = re.split(r"(?=\[\d+\]\s*)", normalized)
    segments: list[tuple[int | None, str]] = []
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        match = _REFERENCE_LABEL_AT_START_RE.match(chunk)
        if match:
            number = int(match.group(1)[1:-1])
            segments.append((number, match.group(2).strip()))
        else:
            segments.append((None, chunk))
    return segments


def _merge_standalone_label_blocks(
    blocks: list[ProcessedBlock],
) -> list[tuple[ProcessedBlock, str]]:
    """Attach orphan ``[N]`` label-only blocks to the following bibliography block."""
    entries: list[tuple[ProcessedBlock, str]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        text = normalize_text(block.text or "")
        if (
            STANDALONE_REFERENCE_LABEL_RE.match(text)
            and index + 1 < len(blocks)
        ):
            next_block = blocks[index + 1]
            next_text = normalize_text(next_block.text or "")
            if next_text and not STANDALONE_REFERENCE_LABEL_RE.match(next_text):
                entries.append((block, f"{text} {next_text}"))
                index += 2
                continue
        entries.append((block, text))
        index += 1
    return entries


def _finalize_reference(
    number: int,
    body_parts: list[str],
    blocks: list[ProcessedBlock],
    confidence: float,
) -> AssembledReference:
    body_text = normalize_text(" ".join(part for part in body_parts if part))
    raw_text = f"[{number}] {body_text}".strip()
    return AssembledReference(
        reference_number=number,
        label=f"[{number}]",
        raw_text=raw_text,
        source_block_ids=_source_ids(blocks),
        page_numbers=sorted({block.page_number for block in blocks}),
        bbox=_union_bbox(blocks),
        confidence=confidence,
    )


def _assemble_from_layout_ordered_blocks(
    blocks: list[ProcessedBlock],
    *,
    confidence: float = 0.85,
) -> list[AssembledReference]:
    """Group bibliography blocks using PDF ``[N]`` anchors in column-major order."""
    ordered_blocks = sort_reference_section_blocks(blocks)
    block_entries = _merge_standalone_label_blocks(ordered_blocks)

    assembled: list[AssembledReference] = []
    current_number: int | None = None
    current_parts: list[str] = []
    current_blocks: list[ProcessedBlock] = []

    def flush_current() -> None:
        nonlocal current_number, current_parts, current_blocks
        if current_number is None:
            return
        assembled.append(
            _finalize_reference(current_number, current_parts, current_blocks, confidence)
        )
        current_number = None
        current_parts = []
        current_blocks = []

    for block, text in block_entries:
        if not text:
            continue

        for number, segment in _iter_block_reference_segments(text):
            if number is None:
                if current_number is not None and segment:
                    current_parts.append(segment)
                    current_blocks.append(block)
                continue

            flush_current()
            current_number = number
            current_blocks = [block]
            current_parts = [segment] if segment else []

    flush_current()
    return assembled


def assemble_references_from_blocks(
    blocks: list[ProcessedBlock],
    *,
    validate: bool = False,
    confidence: float = 0.85,
) -> list[IRNode]:
    """Build IR reference nodes from bibliography-section blocks in layout order."""
    if not blocks:
        return []

    section_start = min(block.page_number for block in blocks)
    section_end = max(block.page_number for block in blocks)
    assembled = _assemble_from_layout_ordered_blocks(blocks, confidence=confidence)
    log_reference_diagnostics(
        assembled,
        section_start_page=section_start,
        section_end_page=section_end,
    )

    if validate:
        validate_reference_sequence(assembled)

    return [
        build_ir_node(
            "REFERENCE",
            ref.raw_text,
            source_block_ids=ref.source_block_ids,
            page_numbers=ref.page_numbers,
            bbox=ref.bbox,
            confidence=ref.confidence,
            label=ref.label,
        )
        for ref in assembled
    ]


def assemble_references_from_buffer(
    buffer: list[tuple[ProcessedBlock, str, float]],
    *,
    validate: bool = False,
) -> list[IRNode]:
    """Build IR reference nodes from buffered bibliography blocks."""
    if not buffer:
        return []
    blocks = [block for block, _, _ in buffer]
    confidence = max((item_confidence for _, _, item_confidence in buffer), default=0.85)
    return assemble_references_from_blocks(blocks, validate=validate, confidence=confidence)


def reference_number_from_mapping_node(
    node: dict | object,
    *,
    text: str | None = None,
    label: str | None = None,
    fallback: int,
) -> int:
    """Resolve the PDF reference number from a mapped or IR node."""
    label_value = label
    text_value = text
    if hasattr(node, "label"):
        label_value = label_value or getattr(node, "label", None)
    elif isinstance(node, dict):
        label_value = label_value or node.get("label")

    if hasattr(node, "text"):
        text_value = text_value or getattr(node, "text", None)
    elif isinstance(node, dict):
        text_value = text_value or node.get("text")

    for candidate in (label_value, text_value):
        number = parse_reference_number(candidate)
        if number is not None:
            return number
    return fallback
