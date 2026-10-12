"""Build Phase 1 :class:`ExtractedDocument` from layout extraction + structure heuristics."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from app.models.document_structure import DocumentStructureResult, ProcessedBlock, StructuredItem
from app.models.extracted_document import (
    ExtractedDocument,
    ExtractedPage,
    ExtractedParagraph,
    ExtractedReferenceItem,
    ExtractedSection,
    ExtractedTableSummary,
    ExtractionQualityIndicators,
    InvalidCharacterReport,
    TextQualitySummary,
)
from app.pipeline.phase1.captions import build_caption_records, collect_caption_candidates
from app.pipeline.phase1.equations import count_inline_math_occurrences, extract_equations
from app.services.layout.semantic_signals import _is_author_bio
from app.utils.reference_assembler import (
    _assemble_from_layout_ordered_blocks,
    collect_reference_section_blocks,
    deduplicate_assembled_references,
    is_plausible_bibliography_entry,
    parse_reference_number,
)
from app.pipeline.phase1.figures import extract_figures
from app.pipeline.phase1.layout_hints import (
    group_paragraph_block_ids,
    multi_column_pages,
    page_column_layout,
)
from app.pipeline.phase1.tables import enrich_tables
from app.models.extraction import ExtractionResult, TextBlock
from app.pipeline.phase1.ir_text import ir_node_plain_text
from app.pipeline.phase1.pdf_kind import classify_pdf_document_kind, quality_warnings
from app.pipeline.phase1.text_fidelity import join_ordered_block_text, scan_text_fidelity
from app.utils.xml_text import strip_illegal_xml_chars
from app.services.layout.block_metrics import block_font_metrics
from app.services.layout.document_pipeline import process_document_structure
from app.services.layout.reading_order import order_document_blocks
from app.services.layout.book_metadata import (
    is_rejected_book_title_candidate,
    normalize_book_author_name,
)
from app.services.layout.book_patterns import looks_like_book_chapter_reference_line
from app.services.layout.semantic_patterns import (
    REFERENCE_HEADING_RE,
    is_roman_section_heading,
    normalize_text,
)
from app.config import settings
from app.pipeline.phase1.extraction_build_options import ExtractionBuildOptions
from app.pipeline.phase1.tables import extract_tables_from_pdf_path


def _heading_kind_for_block(block: ProcessedBlock, body_font: float | None) -> str:
    text = normalize_text((block.text or "").strip())
    if block.classification == "CAPTION":
        return "caption"
    if block.classification == "EQUATION":
        return "equation"
    if block.classification in {"SECTION", "SUBSECTION"}:
        return "section" if block.classification == "SECTION" else "subsection"
    if is_roman_section_heading(text):
        return "section"
    size = block.dominant_font_size
    if size and body_font and size >= body_font + 1.5 and (block.is_bold or len(text) < 120):
        return "heading_candidate"
    return "paragraph"


def _median_body_font(processed: list[ProcessedBlock]) -> float | None:
    sizes = [
        b.dominant_font_size
        for b in processed
        if b.dominant_font_size
        and b.classification in {"PARAGRAPH", "BODY_TEXT", "ABSTRACT"}
        and len((b.text or "").strip()) > 40
    ]
    if not sizes:
        return None
    sizes.sort()
    return sizes[len(sizes) // 2]


def _build_pages(
    raw: ExtractionResult,
    processed_by_id: dict[str, ProcessedBlock],
    body_font: float | None,
) -> list[ExtractedPage]:
    pages_out: list[ExtractedPage] = []
    ordered = order_document_blocks(raw.pages)

    by_page: dict[int, list[tuple[ProcessedBlock | None, TextBlock]]] = {}
    for block, page_number in ordered:
        proc = processed_by_id.get(block.block_id)
        by_page.setdefault(page_number, []).append((proc, block))

    for page in raw.pages:
        paragraphs: list[ExtractedParagraph] = []
        for proc, block in by_page.get(page.page_number, []):
            text = (block.text or "").strip()
            if not text and block.type != "image":
                continue
            if proc and proc.exclude_from_content:
                continue
            kind = "other"
            if proc:
                kind = _heading_kind_for_block(proc, body_font)
            elif text:
                kind = "paragraph"
            font, size, is_bold = block_font_metrics(block)
            paragraphs.append(
                ExtractedParagraph(
                    text=text,
                    kind=kind,
                    source_block_ids=[block.block_id],
                    dominant_font_size=size or (proc.dominant_font_size if proc else None),
                    is_bold=is_bold or (proc.is_bold if proc else False),
                    reading_order_index=proc.reading_order_index if proc else None,
                    column=proc.column if proc else None,
                    bbox=list(block.bbox) if block.bbox else None,
                )
            )

        raw_page_text = join_ordered_block_text(raw, page_number=page.page_number)
        col_layout = page_column_layout(page.width, page.blocks)
        pages_out.append(
            ExtractedPage(
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                char_count=page.text_char_count,
                is_empty=page.page_number in raw.stats.pages_with_no_text,
                requires_ocr=page.requires_ocr,
                column_layout=col_layout,
                paragraphs=paragraphs,
                paragraph_group_block_ids=group_paragraph_block_ids(
                    page.page_number, list(processed_by_id.values())
                ),
                table_ids=[table.table_id for table in page.tables],
                raw_page_text=raw_page_text,
            )
        )
    return pages_out


def _build_sections(structure: DocumentStructureResult) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    for node in structure.sections:
        content_parts = [(item.text or "").strip() for item in node.items if (item.text or "").strip()]
        sections.append(
            ExtractedSection(
                heading=node.heading,
                level=node.level,
                page_number=node.page_number,
                parent_heading=node.parent_heading,
                content="\n\n".join(content_parts),
                source_block_ids=list(node.content_source_block_ids),
            )
        )
    return sections


def _link_captions(
    captions: list,
    tables: list[ExtractedTableSummary],
    figures: list,
) -> None:
    for table in tables:
        if table.caption:
            continue
        for cap in captions:
            if cap.page_number == table.page_number and cap.caption_type == "table":
                table.caption = cap.text
                cap.linked_object_id = table.table_id
                if table.extraction_quality:
                    table.extraction_quality.caption_detected = True
                break
    for figure in figures:
        if figure.caption:
            continue
        for cap in captions:
            if cap.page_number == figure.page_number and cap.caption_type == "figure":
                figure.caption = cap.text
                cap.linked_object_id = figure.figure_id
                if figure.extraction_quality:
                    figure.extraction_quality.caption_detected = True
                break


def _build_book_references(structure: DocumentStructureResult) -> list[ExtractedReferenceItem]:
    by_number: dict[int, ExtractedReferenceItem] = {}
    unnumbered: list[ExtractedReferenceItem] = []
    for item in structure.references:
        text = (item.text or "").strip()
        if not text:
            continue
        if REFERENCE_HEADING_RE.match(normalize_text(text)) or REFERENCE_HEADING_RE.match(
            normalize_text(text.split("\n", 1)[0])
        ):
            continue
        if not looks_like_book_chapter_reference_line(text):
            continue
        entry = ExtractedReferenceItem(
            text=text,
            page_number=item.page_number,
            source_block_ids=list(item.source_block_ids),
        )
        number = parse_reference_number(text)
        if number is None:
            unnumbered.append(entry)
            continue
        if number in by_number:
            logger.info("Removed duplicate reference [%s]", number)
        by_number[number] = entry
    ordered = [by_number[number] for number in sorted(by_number)]
    return ordered + unnumbered


def _structured_items_to_reference_blocks(items: list[StructuredItem]) -> list[ProcessedBlock]:
    blocks: list[ProcessedBlock] = []
    for order, item in enumerate(items):
        text = (item.text or "").strip()
        if not text:
            continue
        if REFERENCE_HEADING_RE.match(normalize_text(text)) or REFERENCE_HEADING_RE.match(
            normalize_text(text.split("\n", 1)[0])
        ):
            continue
        block_id = item.source_block_ids[0] if item.source_block_ids else f"structure_ref_{order}"
        blocks.append(
            ProcessedBlock(
                block_id=block_id,
                page_number=int(item.page_number or 1),
                reading_order_index=order,
                column="FULL_WIDTH",
                classification="REFERENCE_TEXT",
                bbox=list(item.bbox or [0.0, 0.0, 0.0, 0.0]),
                text=text,
                block_type="paragraph",
            )
        )
    return blocks


def _references_from_assembled_blocks(section_blocks: list[ProcessedBlock]) -> list[ExtractedReferenceItem]:
    if not section_blocks:
        return []
    assembled = deduplicate_assembled_references(
        _assemble_from_layout_ordered_blocks(section_blocks)
    )
    ordered = [
        ref
        for ref in assembled
        if ref.reference_number >= 1 and is_plausible_bibliography_entry(ref.raw_text)
    ]
    return [
        ExtractedReferenceItem(
            text=ref.raw_text,
            page_number=ref.page_numbers[0] if ref.page_numbers else 1,
            source_block_ids=list(ref.source_block_ids),
        )
        for ref in ordered
    ]


def _build_references(structure: DocumentStructureResult) -> list[ExtractedReferenceItem]:
    if structure.publication_document_type == "book":
        return _build_book_references(structure)
    block_sem_types = {block.block_id: block.classification for block in structure.blocks}
    section_blocks = collect_reference_section_blocks(
        structure.blocks,
        block_sem_types,
        is_author_bio=_is_author_bio,
    )
    references = _references_from_assembled_blocks(section_blocks)
    source = "layout_section_blocks"
    if not references and structure.references:
        fallback_blocks = _structured_items_to_reference_blocks(structure.references)
        references = _references_from_assembled_blocks(fallback_blocks)
        source = "structure_references_fallback"
    logger.info(
        "[phase1] Reference detection assembled_count=%d structure_items=%d "
        "section_block_count=%d source=%s",
        len(references),
        len(structure.references or []),
        len(section_blocks),
        source,
    )
    return references


def _front_matter_from_semantic(structure: DocumentStructureResult) -> tuple[str | None, list[str]]:
    if structure.publication_document_type == "book":
        title = structure.book_title
        if title and is_rejected_book_title_candidate(title):
            title = None
        authors: list[str] = []
        if structure.book_author:
            normalized = normalize_book_author_name(structure.book_author)
            if normalized:
                authors = [normalized]
        return title, authors
    semantic = structure.semantic
    if not semantic:
        return None, []
    title = ir_node_plain_text(semantic.front.title) or None
    authors: list[str] = []
    for author_node in semantic.front.authors:
        name = ir_node_plain_text(author_node)
        if name:
            authors.append(name)
    return title, authors


def _quality(
    raw: ExtractionResult,
    structure: DocumentStructureResult,
    kind: str,
    tables: list[ExtractedTableSummary],
    figures: list,
    equations: list,
    captions: list,
    references: list[ExtractedReferenceItem],
    sections: list[ExtractedSection],
    multi_column: list[int],
    *,
    inline_equation_count: int = 0,
    invalid_character_report: InvalidCharacterReport | None = None,
    extra_warnings: list[str] | None = None,
) -> ExtractionQualityIndicators:
    completeness = structure.completeness
    retention = None
    if completeness.raw_char_count > 0:
        retention = completeness.retained_char_count / completeness.raw_char_count
    unclassified_ratio = None
    if completeness.retained_char_count > 0:
        unclassified_ratio = (
            completeness.unclassified_char_count / completeness.retained_char_count
        )

    warnings = quality_warnings(raw, kind)
    if extra_warnings:
        warnings.extend(extra_warnings)

    tables_structured = sum(
        1
        for table in tables
        if table.extraction_quality and table.extraction_quality.status == "structured"
    )
    figures_extracted = sum(
        1 for fig in figures if fig.extraction_quality and fig.extraction_quality.image_extracted
    )
    control_count = (
        invalid_character_report.invalid_character_occurrences if invalid_character_report else 0
    )

    return ExtractionQualityIndicators(
        pdf_document_kind=kind,
        page_count=raw.document.page_count,
        extracted_character_count=raw.stats.total_chars,
        invalid_character_report=invalid_character_report,
        text_quality=TextQualitySummary(
            retention_ratio=retention,
            unclassified_ratio=unclassified_ratio,
            multi_column_page_numbers=multi_column,
        ),
        empty_page_numbers=raw.stats.pages_with_no_text,
        low_text_page_numbers=raw.stats.pages_with_low_text,
        requires_ocr=raw.document.requires_ocr,
        ocr_applied=raw.document.ocr_applied,
        text_retention_ratio=retention,
        unclassified_char_ratio=unclassified_ratio,
        detected_section_count=len(sections),
        detected_table_count=len(tables),
        tables_extracted=len(tables),
        tables_structured=tables_structured,
        detected_reference_count=len(references),
        figure_count=len(figures),
        figures_extracted=figures_extracted,
        caption_count=len(captions),
        equation_count=len(equations),
        inline_equation_count=inline_equation_count,
        control_character_count=control_count,
        warnings=warnings,
    )


def build_extracted_document(
    raw: ExtractionResult,
    *,
    structure: DocumentStructureResult | None = None,
    pdf_path: Path | None = None,
    bundle_dir: Path | None = None,
    options: ExtractionBuildOptions | None = None,
) -> ExtractedDocument:
    """Compose Phase 1 IR from raw PyMuPDF extraction (no LLM calls)."""
    opts = options or ExtractionBuildOptions()
    page_count = raw.document.page_count
    auto_fast = page_count >= settings.EXTRACTION_LARGE_PDF_PAGE_THRESHOLD
    fast_mode = opts.fast_tables_figures or auto_fast
    skip_assets = opts.skip_tables_figures

    structure = structure or process_document_structure(raw, include_tagged_output=False)
    processed_by_id = {block.block_id: block for block in structure.blocks}
    body_font = _median_body_font(structure.blocks)

    pages = _build_pages(raw, processed_by_id, body_font)
    sections = _build_sections(structure)
    caption_candidates = collect_caption_candidates(structure.blocks)
    captions = build_caption_records(caption_candidates)
    tables_dir = bundle_dir / "tables" if bundle_dir else None
    figures_dir = bundle_dir / "figures" if bundle_dir else None

    def _page_progress(current: int, total: int) -> None:
        if opts.page_progress:
            opts.page_progress(
                current,
                total,
                f"Processed page {current}/{total} (tables)",
            )

    working_raw = raw
    partial = opts.partial_step4
    if skip_assets:
        tables = []
        figures = []
    else:
        if (
            pdf_path is not None
            and pdf_path.is_file()
            and not any(page.tables for page in raw.pages)
            and not partial
            and not opts.step4_timed_out()
        ):
            working_raw = extract_tables_from_pdf_path(
                pdf_path,
                raw,
                fast_mode=fast_mode,
                page_timeout_sec=opts.table_page_timeout_sec,
                page_progress=_page_progress,
                max_workers=settings.EXTRACTION_TABLE_PAGE_WORKERS,
                should_abort=opts.step4_timed_out,
            )
            if opts.step4_timed_out():
                partial = True
                opts.partial_step4 = True
        elif opts.step4_timed_out():
            partial = True
            opts.partial_step4 = True

        use_fast = fast_mode or partial
        tables = enrich_tables(
            working_raw,
            caption_candidates,
            pdf_path=pdf_path if not use_fast else None,
            assets_dir=tables_dir,
            fast_mode=use_fast,
            skip_heavy_pipeline=partial,
        )
        render_images = not use_fast and not settings.LIGHT_PDF_EXTRACT
        figures = extract_figures(
            pdf_path or Path("__missing__.pdf"),
            working_raw,
            caption_candidates,
            figures_dir=figures_dir if render_images else None,
            path_prefix="figures",
            render_images=render_images,
        ) if pdf_path else []
    equations = extract_equations(structure.blocks)
    inline_equation_count = count_inline_math_occurrences(structure.blocks)
    _link_captions(captions, tables, figures)
    for page in pages:
        page.table_ids = [t.table_id for t in tables if t.page_number == page.page_number]
        page.figure_ids = [f.figure_id for f in figures if f.page_number == page.page_number]
        page.equation_ids = [e.equation_id for e in equations if e.page_number == page.page_number]
    references = _build_references(structure)
    multi_column = multi_column_pages(raw, structure.blocks)
    title, authors = _front_matter_from_semantic(structure)
    pdf_kind = classify_pdf_document_kind(raw)
    document_type = "book" if structure.publication_document_type == "book" else pdf_kind
    raw_text = join_ordered_block_text(raw)
    normalized_text = strip_illegal_xml_chars(raw_text)
    invalid_report = scan_text_fidelity(raw, normalized_text=normalized_text)
    quality_warnings = list(invalid_report.warnings)
    if opts.partial_step4:
        quality_warnings.append(
            "Step 4 exceeded time budget; saved partial table/figure results (fast mode)."
        )
    if skip_assets:
        quality_warnings.append("Tables and figures skipped per extraction request.")

    quality = _quality(
        raw,
        structure,
        pdf_kind,
        tables,
        figures,
        equations,
        captions,
        references,
        sections,
        multi_column,
        inline_equation_count=inline_equation_count,
        invalid_character_report=invalid_report,
        extra_warnings=quality_warnings,
    )

    return ExtractedDocument(
        source_filename=raw.document.filename,
        document_type=document_type,
        publication_document_type=structure.publication_document_type,
        title=title,
        subtitle=structure.book_subtitle if structure.publication_document_type == "book" else None,
        authors=authors,
        publisher=structure.book_publisher,
        publisher_imprint=structure.book_publisher_imprint
        if structure.publication_document_type == "book"
        else None,
        publisher_trade_name=structure.book_publisher_trade_name
        if structure.publication_document_type == "book"
        else None,
        author_blurb=structure.book_author_blurb if structure.publication_document_type == "book" else None,
        author_blurb_inline_elements=list(structure.book_author_blurb_inline_elements)
        if structure.publication_document_type == "book"
        else [],
        legal_notices=list(structure.book_legal_notices)
        if structure.publication_document_type == "book"
        else [],
        toc_entries=list(structure.book_toc_entries)
        if structure.publication_document_type == "book"
        else [],
        publisher_addresses=list(structure.book_publisher_addresses)
        if structure.publication_document_type == "book"
        else [],
        publication_year=structure.book_year,
        isbn=structure.book_isbn,
        isbns=list(structure.book_isbns) if structure.publication_document_type == "book" else [],
        isbn_roles=list(structure.book_isbn_roles) if structure.publication_document_type == "book" else [],
        copyright_holder=structure.book_copyright_holder
        if structure.publication_document_type == "book"
        else None,
        pages=pages,
        sections=sections,
        tables=tables,
        figures=figures,
        equations=equations,
        captions=captions,
        references=references,
        raw_text=raw_text,
        normalized_text=normalized_text,
        extraction_quality=quality,
    )
