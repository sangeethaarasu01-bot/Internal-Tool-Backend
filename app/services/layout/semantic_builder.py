"""Group classified blocks into semantic document elements."""

from __future__ import annotations

import re

from app.models.document_structure import ProcessedBlock
from app.models.extraction import ExtractionResult
from app.models.ir_schema import IRNode
from app.models.semantic_document import (
    SemanticBackMatter,
    SemanticBody,
    SemanticCompletenessReport,
    SemanticDocument,
    SemanticFrontMatter,
    SemanticSection,
)
from app.services.ir_builder import build_abstract, build_display_math, build_ir_node, build_table
from app.utils.math_latex import (
    is_equation_group_boundary,
    is_plausible_display_equation,
    normalize_display_latex,
    split_equation_label,
)
from app.services.layout.semantic_patterns import (
    KEYWORDS_RE,
    REFERENCE_HEADING_RE,
    _CORRESPONDING_AUTHOR_NAME_RE,
    clean_section_heading,
    extract_figure_label,
    extract_leading_roman_section_heading,
    extract_reference_label,
    extract_table_label,
    figure_number_from_label,
    first_line,
    is_explanatory_math_context,
    is_roman_section_heading,
    is_valid_figure_block,
    normalize_text,
    order_authors_with_corresponding,
    parse_author_names,
    parse_figure_caption,
    paragraph_references_figure,
    split_acknowledgment,
    split_merged_headings,
    split_reference_entries,
    split_section_and_body,
    split_section_label_and_title,
)
from app.services.layout.list_detection import (
    ListMarkerInfo,
    collect_list_items,
    expand_multi_marker_list_blocks,
    is_list_continuation,
    merge_list_item_text,
    parse_list_marker,
    reclassify_list_sequences,
    union_bbox,
)
from app.services.layout.semantic_renderer import render_semantic_document
from app.services.layout.semantic_signals import classify_semantic_type
from app.services.layout.table_grid_builder import (
    collect_table_blocks_after_caption,
    reconstruct_table_grid_from_blocks,
)
from app.utils.text_utils import infer_drop_cap_letter, merge_block_texts

LIST_NEST_INDENT = 24.0

MATH_GROUP_GAP = 24.0
MATH_ROW_Y_TOLERANCE = 8.0
MATH_ROW_X_GAP = 45.0
FIGURE_GROUP_GAP = 35.0
LIST_GROUP_GAP = 30.0


def _expand_block_ids(block: ProcessedBlock) -> list[str]:
    return [part.strip() for part in block.block_id.split(",") if part.strip()]


def _mark_mapped(mapped_ids: set[str], block: ProcessedBlock) -> None:
    mapped_ids.update(_expand_block_ids(block))


def _source_ids(blocks: list[ProcessedBlock]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        for part in _expand_block_ids(block):
            if part not in seen:
                seen.add(part)
                ids.append(part)
    return ids


def _element(
    semantic_type: str,
    text: str,
    blocks: list[ProcessedBlock],
    confidence: float = 1.0,
    children: list[IRNode] | None = None,
    keywords: list[str] | None = None,
    heading: str | None = None,
    level: int | None = None,
    unknown_reason: str | None = None,
    label: str | None = None,
    list_type: str | None = None,
    list_marker: str | None = None,
    detection_reason: str | None = None,
    rows: list[list[str]] | None = None,
    drop_cap_letter: str | None = None,
) -> IRNode:
    pages = sorted({b.page_number for b in blocks})
    bbox = union_bbox(blocks) if blocks else None
    if semantic_type == "TABLE" and rows:
        return build_table(
            text,
            rows,
            source_block_ids=_source_ids(blocks),
            page_numbers=pages,
            bbox=bbox,
            confidence=confidence,
            label=label,
        )
    resolved_detection_reason = detection_reason
    if drop_cap_letter:
        resolved_detection_reason = f"drop_cap:{drop_cap_letter}"
    return build_ir_node(
        semantic_type,
        text,
        source_block_ids=_source_ids(blocks),
        page_numbers=pages,
        bbox=bbox,
        confidence=confidence,
        children=children,
        keywords=keywords,
        heading=heading,
        level=level,
        unknown_reason=unknown_reason,
        label=label,
        list_type=list_type,
        list_marker=list_marker,
        detection_reason=resolved_detection_reason,
        rows=rows,
    )


def _merge_text(blocks: list[ProcessedBlock]) -> str:
    return merge_block_texts([block.text for block in blocks])


def _paragraph_text_and_drop_cap(blocks: list[ProcessedBlock]) -> tuple[str, str | None]:
    text = _merge_text(blocks)
    drop_cap_letter = None
    if blocks and len(normalize_text(blocks[0].text)) == 1 and re.fullmatch(r"[A-Z]", normalize_text(blocks[0].text)):
        drop_cap_letter = normalize_text(blocks[0].text)
    if not drop_cap_letter:
        drop_cap_letter = infer_drop_cap_letter(text)
        if drop_cap_letter and not text.startswith(drop_cap_letter):
            text = f"{drop_cap_letter}{text}"
    return text, drop_cap_letter


def _build_list_item_element(
    marker_info: ListMarkerInfo,
    blocks: list[ProcessedBlock],
    confidence: float,
    reason: str,
) -> IRNode:
    content_text = merge_list_item_text(blocks, marker_info)
    paragraph = _element("PARAGRAPH", content_text, blocks, confidence)
    return _element(
        "LIST_ITEM",
        content_text,
        blocks,
        confidence,
        children=[paragraph],
        list_type=marker_info.list_type,
        list_marker=marker_info.marker,
        detection_reason=reason,
    )


def _build_list_element(
    items: list[tuple[ListMarkerInfo, list[ProcessedBlock], float, str]],
) -> IRNode:
    list_type = items[0][0].list_type
    all_blocks = [block for _, blocks, _, _ in items for block in blocks]
    children = [
        _build_list_item_element(marker, blocks, confidence, reason)
        for marker, blocks, confidence, reason in items
    ]
    avg_conf = sum(confidence for _, _, confidence, _ in items) / len(items)
    reasons = sorted({reason for _, _, _, reason in items})
    return _element(
        "LIST",
        " ".join(child.text for child in children),
        all_blocks,
        min(0.98, avg_conf + 0.03),
        children=children,
        list_type=list_type,
        detection_reason="+".join(reasons),
    )




def _parse_keywords(text: str) -> tuple[str, list[str]]:
    cleaned = KEYWORDS_RE.sub("", text).strip(" —-–:")
    keywords = [part.strip() for part in re.split(r",\s*", cleaned) if part.strip()]
    return cleaned, keywords


def _title_font_threshold(blocks: list[ProcessedBlock]) -> float:
    sizes = [b.dominant_font_size or 0 for b in blocks if b.dominant_font_size]
    if not sizes:
        return 16.0
    return max(sizes) - 1.0


def _title_bottom_y(blocks: list[ProcessedBlock], title_ids: set[str]) -> float:
    ys = [b.bbox[3] for b in blocks if b.block_id in title_ids]
    return max(ys) if ys else 0.0


def _can_merge_title(prev: ProcessedBlock, current: ProcessedBlock, threshold: float) -> bool:
    if current.column != "FULL_WIDTH" or prev.column != "FULL_WIDTH":
        return False
    if (current.dominant_font_size or 0) < threshold - 2:
        return False
    if (prev.dominant_font_size or 0) < threshold - 2:
        return False
    vertical_gap = current.bbox[1] - prev.bbox[3]
    return vertical_gap < 40


def _can_merge_author(prev: ProcessedBlock, current: ProcessedBlock) -> bool:
    if prev.column != "FULL_WIDTH" or current.column != "FULL_WIDTH":
        return False
    vertical_gap = current.bbox[1] - prev.bbox[3]
    return vertical_gap < 25


def _paragraph_ends_sentence(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    return bool(re.search(r"(?:[.!?]|\[\d+\])\s*$", normalized))


def _can_merge_paragraph(prev: ProcessedBlock, current: ProcessedBlock) -> bool:
    if extract_leading_roman_section_heading(current.text):
        return False
    if _paragraph_ends_sentence(prev.text):
        return False
    if prev.page_number != current.page_number and prev.page_number + 1 != current.page_number:
        return False
    cross_column = (
        prev.page_number == current.page_number
        and prev.column == "LEFT"
        and current.column == "RIGHT"
    )
    if prev.column != current.column and not cross_column:
        return False
    gap = current.bbox[1] - prev.bbox[3]
    if prev.page_number != current.page_number:
        gap = 0
    if not cross_column and gap > 28:
        return False
    prev_size = prev.dominant_font_size or 10
    cur_size = current.dominant_font_size or 10
    return abs(prev_size - cur_size) <= 1.5


def _merge_drop_cap_blocks(
    enriched: list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]],
) -> list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]]:
    """Attach decorative drop-cap letters to the following paragraph block."""
    merged: list[tuple[ProcessedBlock, str, float, str | None, ListMarkerInfo | None]] = []
    index = 0
    while index < len(enriched):
        block, sem_type, confidence, reason, marker = enriched[index]
        letter = normalize_text(block.text)
        is_drop_cap_candidate = (
            re.fullmatch(r"[A-Z]", letter)
            and (
                (sem_type == "LAYOUT_OBJECT" and reason == "stray_glyph")
                or sem_type == "UNKNOWN_TEXT"
                or reason == "drop_cap_glyph"
                or (sem_type == "PARAGRAPH" and len(letter) == 1)
                or block.is_bold
            )
        )
        if is_drop_cap_candidate and index + 1 < len(enriched):
            next_block, next_type, next_confidence, _, next_marker = enriched[index + 1]
            if next_type == "PARAGRAPH":
                combined = ProcessedBlock(
                    block_id=f"{block.block_id},{next_block.block_id}",
                    page_number=next_block.page_number,
                    reading_order_index=next_block.reading_order_index,
                    column=next_block.column,
                    classification=next_block.classification,
                    confidence=min(confidence, next_confidence),
                    exclude_from_content=next_block.exclude_from_content,
                    exclusion_reason=next_block.exclusion_reason,
                    bbox=union_bbox([block, next_block]),
                    text=f"{letter}{normalize_text(next_block.text)}",
                    block_type=next_block.block_type,
                    dominant_font=next_block.dominant_font,
                    dominant_font_size=next_block.dominant_font_size,
                    is_bold=block.is_bold or next_block.is_bold,
                )
                merged.append((combined, "PARAGRAPH", combined.confidence, f"drop_cap:{letter}", next_marker))
                index += 2
                continue
        merged.append((block, sem_type, confidence, reason, marker))
        index += 1
    return merged


def _vertical_gap(prev: ProcessedBlock, current: ProcessedBlock) -> float:
    if prev.page_number != current.page_number:
        return 0.0
    return current.bbox[1] - prev.bbox[3]


def _math_row_center(block: ProcessedBlock) -> float:
    return (block.bbox[1] + block.bbox[3]) / 2.0


def _same_math_row(left: ProcessedBlock, right: ProcessedBlock) -> bool:
    if left.page_number != right.page_number:
        return False
    return abs(_math_row_center(left) - _math_row_center(right)) <= MATH_ROW_Y_TOLERANCE


def _is_math_semantic_type(sem_type: str) -> bool:
    return sem_type in {"EQUATION", "EQUATION_FRAGMENT"}


def _merge_horizontal_math_rows(
    typed: list[tuple[ProcessedBlock, str, float, str | None]],
) -> list[tuple[ProcessedBlock, str, float, str | None]]:
    """Merge equation fragments that sit on the same visual row (multi-column math)."""
    result: list[tuple[ProcessedBlock, str, float, str | None]] = []
    i = 0
    while i < len(typed):
        block, sem_type, confidence, reason = typed[i]
        if not _is_math_semantic_type(sem_type):
            result.append((block, sem_type, confidence, reason))
            i += 1
            continue

        row: list[tuple[ProcessedBlock, str, float, str | None]] = [
            (block, sem_type, confidence, reason)
        ]
        j = i + 1
        while j < len(typed):
            nxt, nxt_type, nxt_conf, nxt_reason = typed[j]
            if not _same_math_row(block, nxt) or not _is_math_semantic_type(nxt_type):
                break
            prev_block = row[-1][0]
            if nxt.bbox[0] - prev_block.bbox[2] > MATH_ROW_X_GAP:
                break
            row.append((nxt, nxt_type, nxt_conf, nxt_reason))
            j += 1

        if len(row) == 1:
            result.append((block, sem_type, confidence, reason))
            i += 1
            continue

        blocks = sorted((item[0] for item in row), key=lambda candidate: candidate.bbox[0])
        merged = _make_merged_block(blocks)
        avg_conf = sum(item[2] for item in row) / len(row)
        result.append((merged, "EQUATION_FRAGMENT", avg_conf, "horizontal_math_row"))
        i = j

    return result


def _group_equation_fragments(
    typed: list[tuple[ProcessedBlock, str, float, str | None]],
) -> list[tuple[ProcessedBlock, str, float, str | None]]:
    """Merge equation fragments into equation regions, bridging short explanatory lines."""
    result: list[tuple[ProcessedBlock, str, float, str | None]] = []
    i = 0
    while i < len(typed):
        block, sem_type, confidence, reason = typed[i]
        if sem_type != "EQUATION_FRAGMENT":
            result.append((block, sem_type, confidence, reason))
            i += 1
            continue

        group = [block]
        confidences = [confidence]
        j = i + 1
        while j < len(typed):
            nxt, nxt_type, nxt_conf, _ = typed[j]
            if nxt.page_number != group[-1].page_number or nxt.column != group[-1].column:
                break
            gap = _vertical_gap(group[-1], nxt)
            if nxt_type != "EQUATION_FRAGMENT":
                break
            if is_equation_group_boundary(group[-1].text, nxt.text):
                break
            if gap > MATH_GROUP_GAP:
                break
            group.append(nxt)
            confidences.append(nxt_conf)
            j += 1

        if len(group) == 1:
            result.append((group[0], "EQUATION", confidence, None))
        else:
            merged = _make_merged_block(group)
            avg_conf = sum(confidences) / len(confidences)
            result.append((merged, "EQUATION", min(0.88, avg_conf + 0.05), None))
        i = j
    return result


def _make_merged_block(blocks: list[ProcessedBlock]) -> ProcessedBlock:
    """Create a synthetic block representing merged blocks."""
    first = blocks[0]
    last = blocks[-1]
    return ProcessedBlock(
        block_id=",".join(b.block_id for b in blocks),
        page_number=first.page_number,
        reading_order_index=first.reading_order_index,
        column=first.column,
        classification="EQUATION",
        confidence=0.85,
        exclude_from_content=False,
        exclusion_reason=None,
        bbox=[first.bbox[0], first.bbox[1], last.bbox[2], last.bbox[3]],
        text=_merge_text(blocks),
        block_type="text",
        dominant_font=first.dominant_font,
        dominant_font_size=first.dominant_font_size,
        is_bold=first.is_bold,
    )


def _group_figures(
    typed: list[tuple[ProcessedBlock, str, float, str | None]],
) -> list[tuple[ProcessedBlock, str, float, str | None]]:
    """Group nearby FIGURE blocks on the same page into one figure region."""
    result: list[tuple[ProcessedBlock, str, float, str | None]] = []
    i = 0
    while i < len(typed):
        block, sem_type, confidence, reason = typed[i]
        if sem_type != "FIGURE":
            result.append((block, sem_type, confidence, reason))
            i += 1
            continue

        group = [block]
        confidences = [confidence]
        j = i + 1
        while j < len(typed):
            nxt, nxt_type, nxt_conf, _ = typed[j]
            if nxt_type != "FIGURE":
                break
            if nxt.page_number != group[-1].page_number:
                break
            if _vertical_gap(group[-1], nxt) > FIGURE_GROUP_GAP:
                break
            group.append(nxt)
            confidences.append(nxt_conf)
            j += 1

        merged = _make_merged_block(group) if len(group) > 1 else group[0]
        avg_conf = sum(confidences) / len(confidences)
        result.append((merged, "FIGURE", min(0.9, avg_conf + 0.03), None))
        i = j
    return result


def _build_figure_element(
    blocks: list[ProcessedBlock],
    caption_text: str,
    label: str | None,
    confidence: float,
) -> IRNode:
    caption_child = _element("FIGURE_CAPTION", caption_text, blocks, confidence)
    return _element(
        "FIGURE",
        caption_text,
        blocks,
        confidence,
        label=label,
        children=[caption_child],
    )


def _reposition_figures_in_content(content: list[IRNode]) -> list[IRNode]:
    """Place each figure immediately after the paragraph that references it."""
    figures = [node for node in content if node.type == "figure"]
    if not figures:
        return content

    result = list(content)
    for fig in figures:
        fig_num = figure_number_from_label(fig.label)
        if not fig_num:
            continue
        current_pos = result.index(fig)
        target_idx: int | None = None
        for j in range(current_pos - 1, -1, -1):
            if result[j].type == "paragraph" and paragraph_references_figure(result[j].text or "", fig_num):
                target_idx = j
                break
        if target_idx is None:
            for j in range(current_pos + 1, len(result)):
                if result[j].type == "paragraph" and paragraph_references_figure(result[j].text or "", fig_num):
                    target_idx = j
                    break
        if target_idx is None:
            continue
        result.remove(fig)
        result.insert(target_idx + 1, fig)
    return result


def _reposition_figures_in_section(section: SemanticSection) -> None:
    section.content = _reposition_figures_in_content(section.content)
    for subsection in section.subsections:
        _reposition_figures_in_section(subsection)


def _reposition_figures_in_body(body: SemanticBody) -> None:
    for section in body.sections:
        _reposition_figures_in_section(section)


def _attach_figure_captions(
    elements: list[tuple[IRNode, list[ProcessedBlock]]],
) -> list[tuple[IRNode, list[ProcessedBlock]]]:
    """Attach nearest FIGURE_CAPTION to preceding FIGURE."""
    result: list[tuple[IRNode, list[ProcessedBlock]]] = []
    pending_figure: IRNode | None = None
    pending_blocks: list[ProcessedBlock] = []

    for element, blocks in elements:
        if element.type == "figure":
            if pending_figure is not None:
                result.append((pending_figure, pending_blocks))
            pending_figure = element
            pending_blocks = blocks
            continue

        if element.type == "figure_caption" and pending_figure is not None:
            pending_figure.children.append(element)
            pending_blocks.extend(blocks)
            continue

        if pending_figure is not None:
            result.append((pending_figure, pending_blocks))
            pending_figure = None
            pending_blocks = []
        result.append((element, blocks))

    if pending_figure is not None:
        result.append((pending_figure, pending_blocks))
    return result


def build_semantic_document(
    raw: ExtractionResult,
    processed: list[ProcessedBlock],
) -> SemanticDocument:
    body_font = _median_body_size(processed)
    title_threshold = _title_font_threshold(processed)

    typed: list[tuple[ProcessedBlock, str, float, str | None]] = []
    in_references = False
    title_bottom = 0.0
    in_body = False

    for block in processed:
        text = normalize_text(block.text)
        if REFERENCE_HEADING_RE.match(first_line(text)):
            in_references = True

        sem_type, confidence, reason = classify_semantic_type(
            block,
            in_references=in_references,
            body_font_size=body_font,
            title_font_threshold=title_threshold,
            title_bottom_y=title_bottom,
            in_body=in_body,
        )
        typed.append((block, sem_type, confidence, reason))
        if sem_type == "SECTION" and not in_references:
            in_body = True

    title_ids = {b.block_id for b, t, _, _ in typed if t == "TITLE"}
    title_bottom = _title_bottom_y(processed, title_ids)

    typed = _merge_horizontal_math_rows(typed)
    typed = _group_equation_fragments(typed)
    typed = _group_figures(typed)
    enriched = reclassify_list_sequences(typed, in_references=in_references)
    enriched = expand_multi_marker_list_blocks(enriched, in_references=in_references)
    enriched = _merge_drop_cap_blocks(enriched)

    corresponding_author_name: str | None = None
    for block in processed:
        match = _CORRESPONDING_AUTHOR_NAME_RE.search(normalize_text(block.text))
        if match:
            corresponding_author_name = match.group(1).strip()
            break

    front = SemanticFrontMatter()
    body = SemanticBody()
    back = SemanticBackMatter()
    unknown: list[IRNode] = []
    mapped_ids: set[str] = set()
    layout_objects: list[IRNode] = []

    section_stack: list[SemanticSection] = []
    current_section: SemanticSection | None = None
    paragraph_group: list[ProcessedBlock] = []
    pending_reference: IRNode | None = None
    pending_figure_image: ProcessedBlock | None = None
    equation_label_counter = 0

    table_pool: dict[int, list[list[list[str]]]] = {}
    for page in raw.pages:
        page_tables = [table.rows for table in page.tables if len(table.rows) >= 2]
        if page_tables:
            table_pool[page.page_number] = page_tables
    table_cursor: dict[int, int] = {}

    def _next_table_rows(page_number: int) -> list[list[str]] | None:
        tables = table_pool.get(page_number)
        if not tables:
            return None
        index = table_cursor.get(page_number, 0)
        if index >= len(tables):
            return None
        table_cursor[page_number] = index + 1
        return tables[index]

    def current_container() -> SemanticSection | SemanticBody:
        if section_stack:
            return section_stack[-1]
        return body  # type: ignore[return-value]

    def add_content(element: IRNode, blocks: list[ProcessedBlock]) -> None:
        mapped_ids.update(element.source_block_ids)
        container = current_container()
        if isinstance(container, SemanticSection):
            container.content.append(element)
            container.content_source_block_ids.extend(element.source_block_ids)
        else:
            body.loose_paragraphs.append(element)

    def flush_paragraph() -> None:
        nonlocal paragraph_group
        if not paragraph_group:
            return
        paragraph_text, drop_cap_letter = _paragraph_text_and_drop_cap(paragraph_group)
        element = _element(
            "PARAGRAPH",
            paragraph_text,
            paragraph_group,
            0.82,
            drop_cap_letter=drop_cap_letter,
        )
        container = current_container()
        if isinstance(container, SemanticSection):
            container.paragraphs.append(element)
            container.content.append(element)
            container.content_source_block_ids.extend(element.source_block_ids)
        elif back.reference_list is not None:
            back.references.append(element)
        else:
            body.loose_paragraphs.append(element)
        mapped_ids.update(element.source_block_ids)
        paragraph_group = []

    def flush_list() -> None:
        return

    def push_section(heading: str, block: ProcessedBlock, level: int, confidence: float) -> None:
        nonlocal current_section
        flush_paragraph()
        flush_list()
        cleaned_heading = clean_section_heading(heading)
        section_label, section_title = split_section_label_and_title(cleaned_heading)
        heading_el = _element(
            "SUBSECTION" if level > 1 else "SECTION",
            section_title,
            [block],
            confidence,
            heading=section_title,
            level=level,
            label=section_label,
        )
        section = SemanticSection(
            heading=section_title,
            heading_element=heading_el,
            level=level,
            content_source_block_ids=_expand_block_ids(block),
        )
        _mark_mapped(mapped_ids, block)

        if level == 1:
            body.sections.append(section)
            section_stack.clear()
            section_stack.append(section)
            current_section = section
            return

        while len(section_stack) > 1:
            section_stack.pop()
        if section_stack:
            section_stack[0].subsections.append(section)
        else:
            body.sections.append(section)
        section_stack.append(section)
        current_section = section

    def flush_reference() -> None:
        nonlocal pending_reference
        if pending_reference is not None:
            back.references.append(pending_reference)
            mapped_ids.update(pending_reference.source_block_ids)
            pending_reference = None

    i = 0
    while i < len(enriched):
        block, sem_type, confidence, reason, _marker_info = enriched[i]
        block_ids = block.block_id.split(",") if "," in block.block_id else [block.block_id]

        if sem_type == "LAYOUT_OBJECT":
            for bid in block_ids:
                mapped_ids.add(bid)
            layout_objects.append(
                _element("LAYOUT_OBJECT", "", [block], confidence, unknown_reason="decorative_layout_object")
            )
            i += 1
            continue

        if sem_type in {"FOOTER", "RUNNING_HEADER", "PAGE_NUMBER", "JOURNAL_HEADER"}:
            for bid in block_ids:
                mapped_ids.add(bid)
            if sem_type == "JOURNAL_HEADER" and not front.journal_header:
                front.journal_header = _element("JOURNAL_HEADER", "IEEE SENSORS JOURNAL", [block], confidence)
                if re.search(r"\b\d{1,3}\b", normalize_text(block.text)):
                    front.page_number = _element("PAGE_NUMBER", "1", [block], confidence)
            i += 1
            continue

        if sem_type == "TITLE":
            flush_paragraph()
            flush_list()
            flush_reference()
            group = [block]
            while i + 1 < len(enriched):
                nxt, nxt_type, _, _, _ = enriched[i + 1]
                if nxt_type != "TITLE" and not _can_merge_title(group[-1], nxt, title_threshold):
                    break
                if nxt_type == "TITLE" or _can_merge_title(group[-1], nxt, title_threshold):
                    i += 1
                    group.append(nxt)
                    block = nxt
                else:
                    break
            front.title = _element("TITLE", _merge_text(group), group, confidence)
            mapped_ids.update(front.title.source_block_ids)
            i += 1
            continue

        if sem_type == "AUTHOR":
            flush_paragraph()
            flush_list()
            group = [block]
            while i + 1 < len(enriched):
                nxt, nxt_type, _, _, _ = enriched[i + 1]
                if nxt_type == "AUTHOR" and _can_merge_author(group[-1], nxt):
                    i += 1
                    group.append(nxt)
                else:
                    break
            author_blob = _merge_text(group)
            author_names = order_authors_with_corresponding(
                parse_author_names(author_blob),
                corresponding_author_name,
            )
            if not author_names:
                author_names = [author_blob]
            for author_name in author_names:
                element = _element("AUTHOR", author_name, group, confidence)
                front.authors.append(element)
                mapped_ids.update(element.source_block_ids)
            i += 1
            continue

        if sem_type == "AFFILIATION":
            flush_paragraph()
            element = _element("AFFILIATION", normalize_text(block.text), [block], confidence)
            front.affiliations.append(element)
            mapped_ids.update(element.source_block_ids)
            i += 1
            continue

        if sem_type == "DATE_HISTORY":
            flush_paragraph()
            text = normalize_text(block.text)
            corresp_match = re.search(r"\(Corresponding author:[^)]+\)", text, re.I)
            if corresp_match and not front.corresponding_author:
                front.corresponding_author = _element(
                    "CORRESPONDING_AUTHOR",
                    corresp_match.group(0),
                    [block],
                    0.88,
                )
                text = text.replace(corresp_match.group(0), "").strip()
            front.date_history = _element("DATE_HISTORY", text, [block], confidence)
            _mark_mapped(mapped_ids, block)
            i += 1
            continue

        if sem_type == "CORRESPONDING_AUTHOR":
            flush_paragraph()
            front.corresponding_author = _element(
                "CORRESPONDING_AUTHOR", normalize_text(block.text), [block], confidence
            )
            _mark_mapped(mapped_ids, block)
            i += 1
            continue

        if sem_type == "ABSTRACT":
            flush_paragraph()
            text = normalize_text(block.text)
            front.abstract = build_abstract(
                text,
                source_block_ids=_expand_block_ids(block),
                page_numbers=[block.page_number],
                bbox=block.bbox,
                confidence=confidence,
            )
            _mark_mapped(mapped_ids, block)
            i += 1
            continue

        if sem_type == "KEYWORDS":
            flush_paragraph()
            text = normalize_text(block.text)
            _, kw = _parse_keywords(text)
            front.keywords = _element("KEYWORDS", text, [block], confidence, keywords=kw)
            _mark_mapped(mapped_ids, block)
            i += 1
            continue

        if sem_type == "REFERENCE_LIST":
            flush_paragraph()
            flush_list()
            back.reference_list = _element("REFERENCE_LIST", normalize_text(block.text), [block], confidence)
            _mark_mapped(mapped_ids, block)
            in_references = True
            i += 1
            continue

        if sem_type == "SECTION":
            flush_paragraph()
            flush_list()
            flush_reference()
            text = normalize_text(block.text)
            if text.upper().startswith("ACKNOWLEDGMENT"):
                ack_heading, ack_body = split_acknowledgment(text)
                push_section(ack_heading, block, 1, confidence)
                if ack_body:
                    paragraph_group = [block.model_copy(update={"text": ack_body})]
                i += 1
                continue
            headings = [clean_section_heading(h) for h in split_merged_headings(text)]
            section_heading, remainder = split_section_and_body(text)
            if section_heading:
                push_section(clean_section_heading(section_heading), block, 1, confidence)
                if remainder:
                    paragraph_group = [block.model_copy(update={"text": remainder})]
                i += 1
                if len(headings) > 1:
                    push_section(clean_section_heading(headings[1]), block, 2, confidence * 0.95)
                continue
            push_section(clean_section_heading(headings[0]), block, 1, confidence)
            if len(headings) > 1:
                push_section(clean_section_heading(headings[1]), block, 2, confidence * 0.95)
            i += 1
            continue

        if sem_type == "SUBSECTION":
            flush_paragraph()
            flush_list()
            heading = clean_section_heading(first_line(block.text))
            push_section(heading, block, 2, confidence)
            i += 1
            continue

        if sem_type == "REFERENCE":
            flush_paragraph()
            flush_list()
            text = normalize_text(block.text)
            entries = split_reference_entries(text)
            if len(entries) > 1:
                flush_reference()
                for entry_label, entry_body in entries:
                    ref_text = f"{entry_label} {entry_body}".strip() if entry_label else entry_body
                    ref_el = _element(
                        "REFERENCE",
                        ref_text,
                        [block],
                        confidence,
                        label=entry_label or extract_reference_label(ref_text),
                    )
                    back.references.append(ref_el)
                    mapped_ids.update(ref_el.source_block_ids)
                i += 1
                continue

            label = extract_reference_label(text)
            if label and pending_reference is None:
                pending_reference = _element("REFERENCE", text, [block], confidence, label=label)
            elif pending_reference is not None and label is None:
                merged = f"{pending_reference.text} {text}".strip()
                pending_reference.elements = build_ir_node(
                    "REFERENCE", merged, source_block_ids=pending_reference.source_block_ids
                ).elements
                pending_reference.source_block_ids.append(block.block_id)
            else:
                flush_reference()
                pending_reference = _element("REFERENCE", text, [block], confidence, label=label)
            i += 1
            continue

        if sem_type == "LIST_ITEM":
            flush_paragraph()
            flush_list()
            items, next_index = collect_list_items(enriched, i)
            if items:
                list_el = _build_list_element(items)
                add_content(list_el, [block for _, blocks, _, _ in items for block in blocks])
            elif normalize_text(block.text):
                parsed = _marker_info or parse_list_marker(block.text)
                if parsed:
                    list_el = _build_list_element([(parsed, [block], confidence, reason or "ordered_marker")])
                    add_content(list_el, [block])
                else:
                    element = _element("PARAGRAPH", normalize_text(block.text), [block], confidence)
                    body.loose_paragraphs.append(element)
                    mapped_ids.update(element.source_block_ids)
            i = next_index if next_index > i else i + 1
            continue

        if sem_type == "EQUATION":
            flush_paragraph()
            flush_list()
            raw_equation = normalize_text(block.text)
            if not is_plausible_display_equation(raw_equation):
                element = _element("PARAGRAPH", raw_equation, [block], confidence)
                add_content(element, [block])
                i += 1
                continue
            explicit_label, equation_body = split_equation_label(raw_equation)
            equation_label_counter += 1
            label = explicit_label or f"({equation_label_counter})"
            element = build_display_math(
                equation_body,
                source_block_ids=_expand_block_ids(block),
                page_numbers=[block.page_number],
                bbox=block.bbox,
                confidence=confidence,
                label=label,
            )
            add_content(element, [block])
            i += 1
            continue

        if sem_type == "FIGURE":
            flush_paragraph()
            flush_list()
            pending_figure_image = block
            _mark_mapped(mapped_ids, block)
            i += 1
            continue

        if sem_type == "FIGURE_CAPTION":
            flush_paragraph()
            flush_list()
            text = normalize_text(block.text)
            label, caption_text = parse_figure_caption(text)
            if not label:
                label = extract_figure_label(text)
            figure_blocks = [block]
            if pending_figure_image is not None:
                figure_blocks.insert(0, pending_figure_image)
                pending_figure_image = None
            element = _build_figure_element(figure_blocks, caption_text or text, label, confidence)
            add_content(element, figure_blocks)
            for figure_block in figure_blocks:
                _mark_mapped(mapped_ids, figure_block)
            i += 1
            continue

        if sem_type == "TABLE_CAPTION":
            flush_paragraph()
            flush_list()
            text = normalize_text(block.text)
            table_blocks = [block]
            consumed = 0
            rows = _next_table_rows(block.page_number)
            if not rows:
                candidate_blocks, consumed = collect_table_blocks_after_caption(block, enriched, i)
                candidate_rows = reconstruct_table_grid_from_blocks(candidate_blocks)
                if candidate_rows:
                    rows = candidate_rows
                    table_blocks.extend(candidate_blocks)
                else:
                    consumed = 0
            if rows:
                element = _element(
                    "TABLE",
                    text,
                    table_blocks,
                    confidence,
                    label=extract_table_label(text),
                    rows=rows,
                )
            else:
                element = _element(sem_type, text, [block], confidence)
            add_content(element, table_blocks)
            for grid_block in table_blocks[1:]:
                _mark_mapped(mapped_ids, grid_block)
            i += 1 + consumed
            continue

        if sem_type == "EQUATION_FRAGMENT":
            text = normalize_text(block.text)
            if is_explanatory_math_context(text) or (len(text) > 60 and not is_plausible_display_equation(text)):
                sem_type = "PARAGRAPH"

        if (
            sem_type == "UNKNOWN_TEXT"
            and current_section is not None
            and not in_references
            and normalize_text(block.text)
            and reason not in {"excluded_layout_metadata", "decorative_layout_object"}
        ):
            sem_type = "PARAGRAPH"

        if sem_type == "PARAGRAPH":
            flush_list()
            if reason and reason.startswith("drop_cap:"):
                flush_paragraph()
                drop_cap_letter = reason.split(":", 1)[1]
                element = _element(
                    "PARAGRAPH",
                    normalize_text(block.text),
                    [block],
                    confidence,
                    drop_cap_letter=drop_cap_letter,
                )
                container = current_container()
                if isinstance(container, SemanticSection):
                    container.paragraphs.append(element)
                    container.content.append(element)
                    container.content_source_block_ids.extend(element.source_block_ids)
                else:
                    body.loose_paragraphs.append(element)
                mapped_ids.update(element.source_block_ids)
                i += 1
                continue
            if paragraph_group and _can_merge_paragraph(paragraph_group[-1], block):
                paragraph_group.append(block)
            else:
                flush_paragraph()
                paragraph_group = [block]
            i += 1
            continue

        flush_paragraph()
        flush_list()
        element = _element(
            sem_type,
            normalize_text(block.text),
            [block],
            confidence,
            unknown_reason=reason,
        )
        unknown.append(element)
        for bid in block_ids:
            mapped_ids.add(bid)
        i += 1

    flush_paragraph()
    flush_list()
    flush_reference()
    if pending_figure_image is not None:
        _mark_mapped(mapped_ids, pending_figure_image)
        pending_figure_image = None

    _reposition_figures_in_body(body)

    recovery_blocks: list[ProcessedBlock] = []
    for block in processed:
        if block.exclude_from_content or block.block_id in mapped_ids:
            continue
        text = normalize_text(block.text)
        if not text:
            continue
        if REFERENCE_HEADING_RE.match(first_line(text)):
            break
        if is_roman_section_heading(text) and current_section is not None:
            continue
        recovery_blocks.append(block)

    if recovery_blocks and current_section is not None:
        recovery_group: list[ProcessedBlock] = []
        for block in recovery_blocks:
            if recovery_group and not _can_merge_paragraph(recovery_group[-1], block):
                paragraph_group = recovery_group
                flush_paragraph()
                recovery_group = [block]
            else:
                recovery_group.append(block)
        if recovery_group:
            paragraph_group = recovery_group
            flush_paragraph()

    if not front.journal_header:
        for candidate in processed:
            if candidate.page_number != 1 or candidate.exclude_from_content:
                continue
            text = normalize_text(candidate.text)
            if "IEEE SENSORS JOURNAL" in text.upper():
                front.journal_header = _element("JOURNAL_HEADER", "IEEE SENSORS JOURNAL", [candidate], 0.8)
                if re.search(r"\b\d{1,3}\b", text):
                    front.page_number = _element("PAGE_NUMBER", "1", [candidate], 0.8)
                mapped_ids.add(candidate.block_id)
                break

    if front.authors and corresponding_author_name:
        ordered_names = order_authors_with_corresponding(
            [author.text for author in front.authors],
            corresponding_author_name,
        )
        by_text = {author.text: author for author in front.authors}
        front.authors = [by_text[name] for name in ordered_names if name in by_text]

    completeness = _semantic_completeness(raw, processed, mapped_ids, unknown, layout_objects)
    document = SemanticDocument(
        front=front,
        body=body,
        back=back,
        unknown=unknown,
        completeness=completeness,
    )
    document.tagged_output = render_semantic_document(document)
    return document


def _median_body_size(processed: list[ProcessedBlock]) -> float:
    sizes = [
        b.dominant_font_size
        for b in processed
        if b.dominant_font_size and len(normalize_text(b.text)) > 40 and not b.exclude_from_content
    ]
    if not sizes:
        return 10.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def _semantic_completeness(
    raw: ExtractionResult,
    processed: list[ProcessedBlock],
    mapped_ids: set[str],
    unknown: list[IRNode],
    layout_objects: list[IRNode],
) -> SemanticCompletenessReport:
    structured_chars = sum(
        len(normalize_text(b.text))
        for b in processed
        if b.block_id in mapped_ids and not b.exclude_from_content
    )
    excluded_chars = sum(len(normalize_text(b.text)) for b in processed if b.exclude_from_content)
    unmapped = [
        b.block_id
        for b in processed
        if b.block_id not in mapped_ids and not b.exclude_from_content and normalize_text(b.text)
    ]
    return SemanticCompletenessReport(
        raw_character_count=raw.stats.total_chars,
        structured_character_count=structured_chars,
        excluded_character_count=excluded_chars,
        unknown_element_count=len(unknown) + len(unmapped),
        unmapped_block_ids=unmapped,
    )
