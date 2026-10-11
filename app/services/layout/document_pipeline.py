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
from app.services.layout.semantic_patterns import (
    FIGURE_CAPTION_RE,
    LETTER_SUBSECTION_RE,
    REFERENCE_HEADING_RE,
    TABLE_CAPTION_RE,
    extract_leading_roman_section_heading,
    first_line,
    is_letter_subsection_heading,
    is_reference_like_heading,
    is_roman_section_heading,
    normalize_text,
    split_section_and_body,
)
from app.services.layout.book_metadata import BookExtractionContext, detect_book_document
from app.services.layout.book_patterns import (
    looks_like_book_chapter_reference_line,
    parse_book_section_heading,
)
from app.services.layout.text_filter import (
    build_page_number_candidates,
    build_running_footer_candidates,
    build_running_header_candidates,
    classify_content_block,
    collect_author_running_header_prefixes,
)

PIPELINE_VERSION = "2.0.0"
REFS_HEADING = re.compile(r"^\s*REFERENCES\s*$", re.IGNORECASE | re.MULTILINE)
_ROMAN_TOP_SECTION_RE = re.compile(
    r"^(I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s+[A-Z]",
    re.IGNORECASE,
)
_LETTER_SUBSECTION_HEADING_RE = re.compile(r"^[A-Z]\.\s+[A-Za-z]")


def process_document_structure(
    raw: ExtractionResult,
    *,
    include_tagged_output: bool = True,
) -> DocumentStructureResult:
    running_headers = build_running_header_candidates(raw)
    running_footers = build_running_footer_candidates(raw)
    page_numbers = build_page_number_candidates(raw)
    author_header_prefixes = collect_author_running_header_prefixes(raw)
    book_ctx = detect_book_document(raw)

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
        if book_ctx.is_book and parse_book_section_heading(text):
            in_references = False
        elif REFERENCE_HEADING_RE.match(normalize_text(text)) or REFERENCE_HEADING_RE.match(
            first_line(text)
        ):
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
            author_header_prefixes,
            running_footers,
            book_mode=book_ctx.is_book,
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

    from app.utils.proof_pdf import apply_author_query_cover_exclusions

    processed_blocks = apply_author_query_cover_exclusions(raw, processed_blocks)

    completeness = _build_completeness_report(raw, processed_blocks)
    sections, paragraphs, references, unknown_items = _build_structure(
        processed_blocks,
        book_ctx=book_ctx,
    )
    if not book_ctx.is_book:
        chapter_like = sum(
            1
            for section in sections
            if section.level == 1
            and (
                section.heading.lower().startswith("chapter ")
                or section.heading.lower().startswith("intermission ")
            )
        )
        if chapter_like >= 5 and len(raw.pages) >= 40:
            from app.services.layout.book_metadata import _extract_metadata_from_raw

            book_ctx = _extract_metadata_from_raw(raw)
            sections, paragraphs, references, unknown_items = _build_structure(
                processed_blocks,
                book_ctx=book_ctx,
            )
    stats = _build_stats(processed_blocks, sections, paragraphs, references, unknown_items)
    semantic = build_semantic_document(
        raw,
        processed_blocks,
        include_tagged_output=include_tagged_output,
        book_ctx=book_ctx,
    )

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
        publication_document_type=book_ctx.publication_document_type,
        book_title=book_ctx.title,
        book_author=book_ctx.author,
        book_publisher=book_ctx.publisher,
        book_year=book_ctx.year,
        book_isbn=book_ctx.isbn,
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


def _column_reading_index(block: ProcessedBlock) -> int:
    """Left / full-width column before right column on the same page."""
    column = (block.column or "LEFT").upper()
    if column == "RIGHT":
        return 1
    return 0


def _spatial_block_key(block: ProcessedBlock) -> tuple[float, float, float, float]:
    bbox = block.bbox or [0.0, 0.0, 0.0, 0.0]
    return (
        float(block.page_number),
        float(_column_reading_index(block)),
        float(bbox[1]),
        float(bbox[0]),
    )


def _section_heading_level(
    block: ProcessedBlock,
    text: str,
    *,
    in_references: bool = False,
    book_mode: bool = False,
) -> int | None:
    line = first_line(text)
    if book_mode and parse_book_section_heading(text):
        return 1
    if is_reference_like_heading(text, in_references=in_references):
        return None
    if block.classification == "SUBSECTION":
        return 2
    if block.classification == "SECTION":
        return 1
    if block.classification not in {"CAPTION", "FIGURE"} and _LETTER_SUBSECTION_HEADING_RE.match(line):
        if len(line.split()) <= 14:
            return 2
    if is_letter_subsection_heading(text, block):
        return 2
    if _ROMAN_TOP_SECTION_RE.match(line) or is_roman_section_heading(text):
        return 1
    if extract_leading_roman_section_heading(text):
        return 1
    return None


def _is_subsection_heading_continuation(line: str) -> bool:
    words = line.split()
    if not words or len(words) > 12:
        return False
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return upper_ratio >= 0.8


def _parse_embedded_letter_subsection(
    text: str,
    block: ProcessedBlock,
) -> tuple[str | None, str | None, list[str]]:
    """Split ``II. SECTION\\nA. SUBSECTION`` (and optional body) from one block."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None, None, lines
    if not LETTER_SUBSECTION_RE.match(lines[1]) and not is_letter_subsection_heading(lines[1], block):
        return None, None, lines
    heading = lines[1]
    index = 2
    while index < len(lines) and _is_subsection_heading_continuation(lines[index]):
        if LETTER_SUBSECTION_RE.match(lines[index]):
            break
        heading = f"{heading} {lines[index]}"
        index += 1
    body = "\n".join(lines[index:]).strip() if index < len(lines) else None
    return heading, body or None, lines[:1]


def _section_heading_text(
    block: ProcessedBlock,
    text: str,
    level: int,
    *,
    book_mode: bool = False,
) -> str:
    if book_mode:
        parsed = parse_book_section_heading(text)
        if parsed:
            return parsed.heading
    if level == 1:
        split_heading = extract_leading_roman_section_heading(text)
        if split_heading:
            return split_heading
        return first_line(text)
    return first_line(text)


def _is_caption_like_block(block: ProcessedBlock, text: str) -> bool:
    line = normalize_text(first_line(text))
    if FIGURE_CAPTION_RE.match(line):
        return True
    if TABLE_CAPTION_RE.match(line):
        return True
    if block.classification == "FIGURE":
        return True
    if block.classification == "CAPTION":
        return bool(FIGURE_CAPTION_RE.match(line) or TABLE_CAPTION_RE.match(line))
    return False


def _build_structure(
    processed: list[ProcessedBlock],
    *,
    book_ctx: BookExtractionContext | None = None,
) -> tuple[list[SectionNode], list[StructuredItem], list[StructuredItem], list[StructuredItem]]:
    book_mode = bool(book_ctx and book_ctx.is_book)
    paragraphs: list[StructuredItem] = []
    references: list[StructuredItem] = []
    unknown_items: list[StructuredItem] = []

    ordered = sorted(
        [b for b in processed if not b.exclude_from_content],
        key=_spatial_block_key,
    )

    heading_nodes: list[SectionNode] = []
    heading_keys: list[list[float]] = []
    heading_block_ids: set[str] = set()
    blocks_by_id = {block.block_id: block for block in processed}
    last_roman_heading: str | None = None
    in_references = False

    for block in ordered:
        text = (block.text or "").strip()
        if not text and block.block_type != "image":
            continue

        if book_mode and parse_book_section_heading(text):
            in_references = False
        elif REFERENCE_HEADING_RE.match(normalize_text(text)) or REFERENCE_HEADING_RE.match(
            first_line(text)
        ):
            in_references = True
            continue

        heading_level = _section_heading_level(
            block, text, in_references=in_references, book_mode=book_mode
        )
        if heading_level is not None:
            in_references = False
            heading = _section_heading_text(
                block, text, heading_level, book_mode=book_mode
            )
            parent = None
            if heading_level == 1:
                last_roman_heading = heading
            else:
                parent = last_roman_heading
            node = SectionNode(
                heading=heading,
                heading_block_ids=[block.block_id],
                level=heading_level,
                page_number=block.page_number,
                parent_heading=parent,
                spatial_key=[*map(float, _spatial_block_key(block))],
            )
            heading_nodes.append(node)
            heading_keys.append([*map(float, _spatial_block_key(block))])
            heading_block_ids.add(block.block_id)

            if heading_level == 1:
                _, body_after_heading = split_section_and_body(text)
                body_after_heading = body_after_heading or ""
                embedded_heading, embedded_body, _ = _parse_embedded_letter_subsection(text, block)
                if embedded_heading:
                    sub_node = SectionNode(
                        heading=embedded_heading,
                        heading_block_ids=[block.block_id],
                        level=2,
                        page_number=block.page_number,
                        parent_heading=last_roman_heading,
                        spatial_key=[*map(float, _spatial_block_key(block))],
                    )
                    heading_nodes.append(sub_node)
                    heading_keys.append([*map(float, _spatial_block_key(block))])
                    if embedded_body:
                        item = StructuredItem(
                            type="paragraph",
                            text=embedded_body,
                            page_number=block.page_number,
                            source_block_ids=[block.block_id],
                            content_source_block_ids=[block.block_id],
                            bbox=block.bbox,
                        )
                        paragraphs.append(item)
                        sub_node.items.append(item)
                        sub_node.content_source_block_ids.append(block.block_id)
                elif body_after_heading.strip():
                    item = StructuredItem(
                        type="paragraph",
                        text=body_after_heading.strip(),
                        page_number=block.page_number,
                        source_block_ids=[block.block_id],
                        content_source_block_ids=[block.block_id],
                        bbox=block.bbox,
                    )
                    paragraphs.append(item)
                    node.items.append(item)
                    node.content_source_block_ids.append(block.block_id)

    def _heading_bbox_y0(node: SectionNode) -> float | None:
        for block_id in node.heading_block_ids:
            block = blocks_by_id.get(block_id)
            if block and block.bbox and len(block.bbox) >= 4:
                return float(block.bbox[1])
        if node.spatial_key and len(node.spatial_key) >= 3:
            return float(node.spatial_key[2])
        return None

    def _heading_bbox_y1(node: SectionNode) -> float | None:
        for block_id in node.heading_block_ids:
            block = blocks_by_id.get(block_id)
            if block and block.bbox and len(block.bbox) >= 4:
                return float(block.bbox[3])
        return _heading_bbox_y0(node)

    def _first_child_on_same_page(index: int) -> SectionNode | None:
        current = heading_nodes[index]
        if current.level != 1:
            return None
        for child in heading_nodes[index + 1 :]:
            if child.level == 2 and child.parent_heading == current.heading:
                if child.page_number == current.page_number:
                    return child
                return None
            if child.level == 1:
                break
        return None

    def _heading_span_end_key(index: int) -> list[float] | None:
        current = heading_nodes[index]
        if current.level == 1:
            for child in heading_nodes[index + 1 :]:
                if child.level == 2 and child.parent_heading == current.heading:
                    return child.spatial_key
                if child.level == 1:
                    return child.spatial_key
            return None
        if index + 1 < len(heading_nodes):
            return heading_nodes[index + 1].spatial_key
        return None

    def _assign_section_index(block: ProcessedBlock) -> int | None:
        if not heading_keys:
            return None
        match: int | None = None
        block_key = _spatial_block_key(block)
        bk = tuple(block_key)
        bbox = block.bbox or [0.0, 0.0, 0.0, 0.0]
        block_top = float(bbox[1])
        for index, key in enumerate(heading_keys):
            hk = tuple(key)
            if bk < hk:
                continue
            child = _first_child_on_same_page(index)
            if child is not None:
                y_lo = _heading_bbox_y1(heading_nodes[index])
                y_hi = _heading_bbox_y0(child)
                if (
                    block.page_number == heading_nodes[index].page_number
                    and y_lo is not None
                    and y_hi is not None
                ):
                    if block_top < y_lo - 0.5 or block_top >= y_hi - 0.5:
                        continue
                    match = index
                    break
            end_key = _heading_span_end_key(index)
            if end_key is not None and bk >= tuple(end_key):
                continue
            match = index
        return match

    in_references = False
    for block in ordered:
        text = (block.text or "").strip()
        if not text and block.block_type != "image":
            continue

        if book_mode and parse_book_section_heading(text):
            in_references = False
        elif REFERENCE_HEADING_RE.match(normalize_text(text)) or REFERENCE_HEADING_RE.match(
            first_line(text)
        ):
            in_references = True
            continue

        if block.block_id in heading_block_ids:
            continue
        if _is_caption_like_block(block, text):
            continue

        item = StructuredItem(
            type=block.classification.lower(),
            text=block.text,
            page_number=block.page_number,
            source_block_ids=[block.block_id],
            content_source_block_ids=[block.block_id],
            bbox=block.bbox,
        )

        if in_references:
            if book_mode and not looks_like_book_chapter_reference_line(text):
                pass
            else:
                references.append(item)
                continue

        section_index = _assign_section_index(block)
        target = heading_nodes[section_index] if section_index is not None else None

        if block.classification in {"PARAGRAPH", "BODY_TEXT", "ABSTRACT", "TITLE", "AUTHOR"}:
            paragraphs.append(item)
            if target:
                target.items.append(item)
                target.content_source_block_ids.append(block.block_id)
            continue

        if block.classification == "UNKNOWN_TEXT":
            unknown_items.append(item)
            if target:
                target.items.append(item)
                target.content_source_block_ids.append(block.block_id)
            continue

        paragraphs.append(item)
        if target:
            target.items.append(item)
            target.content_source_block_ids.append(block.block_id)

    def _rebuild_level_one_intro_spans() -> None:
        for index, node in enumerate(heading_nodes):
            if node.level != 1:
                continue
            child = _first_child_on_same_page(index)
            if child is None:
                continue
            y_lo = _heading_bbox_y1(node)
            y_hi = _heading_bbox_y0(child)
            if y_lo is None or y_hi is None:
                continue
            intro_items: list[StructuredItem] = []
            stolen_ids: set[str] = set()
            for block in ordered:
                if block.page_number != node.page_number:
                    continue
                if block.block_id in heading_block_ids:
                    continue
                if not block.bbox or len(block.bbox) < 4:
                    continue
                if _is_caption_like_block(block, (block.text or "").strip()):
                    continue
                block_top = float(block.bbox[1])
                if block_top < y_lo - 0.5 or block_top >= y_hi - 0.5:
                    continue
                text = (block.text or "").strip()
                if not text and block.block_type != "image":
                    continue
                intro_items.append(
                    StructuredItem(
                        type=block.classification.lower(),
                        text=block.text,
                        page_number=block.page_number,
                        source_block_ids=[block.block_id],
                        content_source_block_ids=[block.block_id],
                        bbox=block.bbox,
                    )
                )
                stolen_ids.add(block.block_id)
            if not intro_items:
                continue
            node.items = intro_items
            node.content_source_block_ids = list(stolen_ids)
            for other in heading_nodes:
                if other is node:
                    continue
                other.items = [
                    item
                    for item in other.items
                    if not any(bid in stolen_ids for bid in item.content_source_block_ids)
                ]
                other.content_source_block_ids = [
                    block_id
                    for block_id in other.content_source_block_ids
                    if block_id not in stolen_ids
                ]

    _rebuild_level_one_intro_spans()

    def _attach_paragraph_above_roman_heading() -> None:
        for node in heading_nodes:
            if node.level != 1 or node.items:
                continue
            y_lo = _heading_bbox_y0(node)
            if y_lo is None:
                continue
            heading_block = blocks_by_id.get(node.heading_block_ids[0]) if node.heading_block_ids else None
            heading_column = (heading_block.column or "LEFT").upper() if heading_block else "LEFT"
            best_block: ProcessedBlock | None = None
            best_gap = 9999.0
            for block in ordered:
                if block.page_number != node.page_number:
                    continue
                if block.block_id in heading_block_ids:
                    continue
                if (block.column or "LEFT").upper() != heading_column:
                    continue
                if not block.bbox or len(block.bbox) < 4:
                    continue
                if _is_caption_like_block(block, (block.text or "").strip()):
                    continue
                text = (block.text or "").strip()
                if not text or is_reference_like_heading(text):
                    continue
                if _section_heading_level(block, text, in_references=False) is not None:
                    continue
                block_bottom = float(block.bbox[3])
                gap = y_lo - block_bottom
                if gap < -2 or gap > 80:
                    continue
                if gap < best_gap:
                    best_gap = gap
                    best_block = block
            if best_block is None:
                continue
            stolen_ids = {best_block.block_id}
            for other in heading_nodes:
                other.items = [
                    item
                    for item in other.items
                    if not any(bid in stolen_ids for bid in item.content_source_block_ids)
                ]
                other.content_source_block_ids = [
                    bid for bid in other.content_source_block_ids if bid not in stolen_ids
                ]
            item = StructuredItem(
                type=best_block.classification.lower(),
                text=best_block.text,
                page_number=best_block.page_number,
                source_block_ids=[best_block.block_id],
                content_source_block_ids=[best_block.block_id],
                bbox=best_block.bbox,
            )
            node.items.append(item)
            node.content_source_block_ids.append(best_block.block_id)

    _attach_paragraph_above_roman_heading()

    conclusion_re = re.compile(r"^\s*V\.\s+CONCLUSION", re.IGNORECASE)
    for section in heading_nodes:
        if not conclusion_re.match(section.heading.strip()):
            continue
        trimmed: list[StructuredItem] = []
        for item in section.items:
            item_text = (item.text or "").strip()
            if REFERENCE_HEADING_RE.match(normalize_text(item_text)) or REFERENCE_HEADING_RE.match(
                first_line(item_text)
            ):
                break
            if item.type == "reference_text":
                break
            trimmed.append(item)
        section.items = trimmed
        section.content_source_block_ids = [
            block_id
            for item in trimmed
            for block_id in item.content_source_block_ids
        ]

    sections: list[SectionNode] = []
    for index, node in enumerate(heading_nodes):
        if node.level != 1:
            continue
        sections.append(node)
        end_key = None
        for later in heading_nodes[index + 1 :]:
            if later.level == 1:
                end_key = later.spatial_key
                break
        children: list[SectionNode] = []
        for child in heading_nodes:
            if child.level != 2 or child.parent_heading != node.heading:
                continue
            if child.spatial_key is None:
                continue
            if tuple(child.spatial_key) < tuple(node.spatial_key or [0, 0, 0]):
                continue
            if end_key is not None and tuple(child.spatial_key) >= tuple(end_key):
                continue
            children.append(child)
        children.sort(key=lambda c: tuple(c.spatial_key or [0, 0, 0]))
        sections.extend(children)

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


def build_full_extraction_result(
    raw: ExtractionResult,
    *,
    include_tagged_output: bool = True,
) -> ExtractionResult:
    structure = process_document_structure(raw, include_tagged_output=include_tagged_output)
    return raw.model_copy(update={"structure": structure})
