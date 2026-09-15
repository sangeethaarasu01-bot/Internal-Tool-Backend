"""Raw extraction -> filter -> reading order -> structure -> completeness report."""

from __future__ import annotations

import re

from app.models.document_structure import (
    CompletenessReport,
    DocumentStructureResult,
    ExcludedBlock,
    ProcessedBlock,
    SectionNode,
    StructuredItem,
    StructureStats,
)
from app.models.extraction import ExtractionResult, TextBlock
from app.services.layout.block_metrics import block_font_metrics, median_body_font_size
from app.services.layout.column_classifier import classify_block_column
from app.services.layout.reading_order import order_document_blocks
from app.services.layout.semantic_builder import build_semantic_document
from app.services.layout.text_filter import (
    build_page_number_candidates,
    build_running_header_candidates,
    classify_content_block,
)

PIPELINE_VERSION = "2.0.0"
REFS_HEADING = re.compile(r"^\s*REFERENCES\s*$", re.IGNORECASE | re.MULTILINE)


def process_document_structure(raw: ExtractionResult) -> DocumentStructureResult:
    running_headers = build_running_header_candidates(raw)
    page_numbers = build_page_number_candidates(raw)

    ordered_pairs = order_document_blocks(raw.pages)
    page_by_number = {page.page_number: page for page in raw.pages}

    body_font_size = median_body_font_size(
        [(block, "PARAGRAPH") for block, _page_number in ordered_pairs if (block.text or "").strip()]
    )

    processed_blocks: list[ProcessedBlock] = []
    in_references = False

    for index, (block, page_number) in enumerate(ordered_pairs):
        page = page_by_number[page_number]
        column = classify_block_column(block, page.width)
        text = (block.text or "").strip()
        if text.upper() == "REFERENCES":
            in_references = True

        decision = classify_content_block(
            block,
            page_number,
            page.width,
            page.height,
            in_references,
            running_headers,
            page_numbers,
            body_font_size,
        )

        if decision.classification in {"BODY_TEXT", "UNKNOWN_TEXT"} and len(text) > 20:
            decision.classification = "PARAGRAPH"

        font, size, is_bold = block_font_metrics(block)
        processed_blocks.append(
            ProcessedBlock(
                block_id=block.block_id,
                page_number=page_number,
                reading_order_index=index,
                column=column,
                classification=decision.classification,
                confidence=decision.confidence,
                exclude_from_content=decision.exclude_from_content,
                exclusion_reason=decision.exclusion_reason,
                bbox=block.bbox,
                text=block.text,
                block_type=block.type,
                dominant_font=font,
                dominant_font_size=size,
                is_bold=is_bold,
            )
        )

    completeness = _build_completeness_report(raw, processed_blocks)
    sections, paragraphs, references, unknown_items = _build_structure(processed_blocks)
    stats = _build_stats(processed_blocks, sections, paragraphs, references, unknown_items)
    semantic = build_semantic_document(raw, processed_blocks)

    return DocumentStructureResult(
        pipeline_version=PIPELINE_VERSION,
        blocks=processed_blocks,
        sections=sections,
        paragraphs=paragraphs,
        references=references,
        unknown_items=unknown_items,
        completeness=completeness,
        structure_stats=stats,
        semantic=semantic,
    )


def _build_completeness_report(
    raw: ExtractionResult,
    processed: list[ProcessedBlock],
) -> CompletenessReport:
    raw_chars = raw.stats.total_chars
    excluded_blocks: list[ExcludedBlock] = []
    summary: dict[str, int] = {}

    for block in processed:
        if not block.exclude_from_content:
            continue
        chars = len((block.text or "").strip())
        excluded_blocks.append(
            ExcludedBlock(
                block_id=block.block_id,
                page_number=block.page_number,
                classification=block.classification,
                reason=block.exclusion_reason or "excluded",
                text=block.text,
                char_count=chars,
                bbox=block.bbox,
            )
        )
        key = block.classification
        summary[key] = summary.get(key, 0) + chars

    excluded_chars = sum(item.char_count for item in excluded_blocks)
    retained_chars = sum(
        len((b.text or "").strip())
        for b in processed
        if not b.exclude_from_content
    )
    unclassified_chars = sum(
        len((b.text or "").strip())
        for b in processed
        if not b.exclude_from_content
        and b.classification in {"UNKNOWN_TEXT", "BODY_TEXT"}
    )

    return CompletenessReport(
        raw_char_count=raw_chars,
        retained_char_count=retained_chars,
        excluded_char_count=excluded_chars,
        unclassified_char_count=unclassified_chars,
        excluded_blocks=excluded_blocks,
        exclusion_summary=summary,
    )


def _build_structure(
    processed: list[ProcessedBlock],
) -> tuple[list[SectionNode], list[StructuredItem], list[StructuredItem], list[StructuredItem]]:
    sections: list[SectionNode] = []
    paragraphs: list[StructuredItem] = []
    references: list[StructuredItem] = []
    unknown_items: list[StructuredItem] = []

    current_section: SectionNode | None = None

    for block in processed:
        if block.exclude_from_content:
            continue

        text = (block.text or "").strip()
        if not text and block.block_type != "image":
            continue

        item = StructuredItem(
            type=block.classification.lower(),
            text=block.text,
            page_number=block.page_number,
            source_block_ids=[block.block_id],
            content_source_block_ids=[block.block_id],
            bbox=block.bbox,
        )

        if block.classification in {"SECTION", "SUBSECTION"}:
            current_section = SectionNode(
                heading=text,
                heading_block_ids=[block.block_id],
                level=2 if block.classification == "SUBSECTION" else 1,
                page_number=block.page_number,
            )
            sections.append(current_section)
            continue

        if block.classification == "REFERENCE_TEXT":
            references.append(item)
            if current_section:
                current_section.items.append(item)
                current_section.content_source_block_ids.append(block.block_id)
            continue

        if block.classification in {"PARAGRAPH", "BODY_TEXT", "ABSTRACT", "TITLE", "AUTHOR"}:
            paragraphs.append(item)
            if current_section:
                current_section.items.append(item)
                current_section.content_source_block_ids.append(block.block_id)
            continue

        if block.classification == "UNKNOWN_TEXT":
            unknown_items.append(item)
            if current_section:
                current_section.items.append(item)
                current_section.content_source_block_ids.append(block.block_id)
            continue

        paragraphs.append(item)
        if current_section:
            current_section.items.append(item)
            current_section.content_source_block_ids.append(block.block_id)

    return sections, paragraphs, references, unknown_items


def _build_stats(
    processed: list[ProcessedBlock],
    sections: list[SectionNode],
    paragraphs: list[StructuredItem],
    references: list[StructuredItem],
    unknown_items: list[StructuredItem],
) -> StructureStats:
    return StructureStats(
        detected_sections=len(sections),
        detected_paragraphs=len(paragraphs),
        detected_references=len(references),
        unknown_blocks=len(unknown_items),
        running_headers=sum(
            1 for b in processed if b.classification == "RUNNING_HEADER"
        ),
        page_numbers=sum(1 for b in processed if b.classification == "PAGE_NUMBER"),
        footers=sum(1 for b in processed if b.classification == "FOOTER"),
    )


def build_full_extraction_result(raw: ExtractionResult) -> ExtractionResult:
    structure = process_document_structure(raw)
    return raw.model_copy(update={"structure": structure})
