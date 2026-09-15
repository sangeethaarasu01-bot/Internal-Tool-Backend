"""Signal extraction from processed blocks for semantic classification."""

from __future__ import annotations

import re

from app.models.document_structure import ProcessedBlock

from app.services.layout.list_detection import is_likely_heading_not_list, parse_list_marker
from app.services.layout.semantic_patterns import (
    ABSTRACT_RE,
    ACKNOWLEDGMENT_RE,
    AFFILIATION_RE,
    CITATION_RE,
    CORRESPONDING_RE,
    DATE_HISTORY_RE,
    FIGURE_CAPTION_RE,
    JOURNAL_HEADER_RE,
    KEYWORDS_RE,
    REFERENCE_HEADING_RE,
    TABLE_CAPTION_RE,
    is_table_continuation_heading,
    block_height,
    first_line,
    is_author_candidate,
    is_decorative_layout_object,
    is_explanatory_math_context,
    is_letter_subsection_heading,
    is_list_item,
    is_math_fragment,
    is_numbered_subsection_heading,
    is_standalone_equation_text,
    is_roman_section_heading,
    is_title_candidate,
    is_valid_figure_block,
    normalize_text,
)

AUTHOR_BIO_RE = re.compile(
    r"(?:received the|is a Research Scholar|is currently|is working as|"
    r"His key research|Her research|certified Data Scientist)",
    re.IGNORECASE,
)


def _is_author_bio(text: str) -> bool:
    return bool(AUTHOR_BIO_RE.search(text))


def classify_semantic_type(
    block: ProcessedBlock,
    *,
    in_references: bool,
    body_font_size: float,
    title_font_threshold: float,
    title_bottom_y: float,
    in_body: bool = False,
) -> tuple[str, float, str | None]:
    """Return (semantic_type, confidence, unknown_reason)."""
    text = normalize_text(block.text)
    line = first_line(block.text)

    if JOURNAL_HEADER_RE.search(text) and block.page_number == 1 and block.column == "FULL_WIDTH":
        return "JOURNAL_HEADER", 0.92, None

    if block.exclude_from_content:
        if block.classification == "FOOTER":
            return "FOOTER", 0.95, None
        if block.classification == "RUNNING_HEADER":
            return "RUNNING_HEADER", 0.9, None
        if block.classification == "PAGE_NUMBER":
            return "PAGE_NUMBER", 0.9, None
        return "UNKNOWN_TEXT", 0.35, "excluded_layout_metadata"

    if is_decorative_layout_object(block):
        return "LAYOUT_OBJECT", 0.85, None

    if is_valid_figure_block(block):
        return "FIGURE", 0.82, None

    if not text and block.block_type == "image":
        return "LAYOUT_OBJECT", 0.7, "empty_image_block"

    if REFERENCE_HEADING_RE.match(line):
        return "REFERENCE_LIST", 0.96, None

    if ACKNOWLEDGMENT_RE.match(line):
        return "SECTION", 0.88, None

    if _is_author_bio(text):
        return "PARAGRAPH", 0.76, "author_bio"

    if in_references:
        return "REFERENCE", 0.86, None

    if block.classification == "REFERENCE_TEXT" and CITATION_RE.search(text):
        return "REFERENCE", 0.84, None

    if ABSTRACT_RE.match(text):
        return "ABSTRACT", 0.95, None

    if KEYWORDS_RE.match(text):
        return "KEYWORDS", 0.95, None

    if DATE_HISTORY_RE.match(text):
        return "DATE_HISTORY", 0.9, None

    if CORRESPONDING_RE.search(text):
        return "CORRESPONDING_AUTHOR", 0.9, None

    if AFFILIATION_RE.search(text) and block.page_number == 1:
        return "AFFILIATION", 0.82, None

    if is_author_candidate(block, title_bottom_y):
        return "AUTHOR", 0.86, None

    if is_title_candidate(block, title_font_threshold):
        return "TITLE", 0.87, None

    if FIGURE_CAPTION_RE.match(line):
        return "FIGURE_CAPTION", 0.88, None

    if TABLE_CAPTION_RE.match(line) or is_table_continuation_heading(text):
        return "TABLE_CAPTION", 0.86, None

    if is_roman_section_heading(text):
        return "SECTION", 0.93, None

    list_marker = parse_list_marker(text, in_references=in_references)
    if list_marker and not is_likely_heading_not_list(text, block, in_body=in_body):
        return "LIST_ITEM", 0.84, None

    if is_letter_subsection_heading(text, block):
        return "SUBSECTION", 0.91, None

    if is_numbered_subsection_heading(text):
        return "SUBSECTION", 0.89, None

    if block.classification == "SUBSECTION" and is_letter_subsection_heading(text, block):
        return "SUBSECTION", 0.88, None

    if block.classification == "SECTION" and is_roman_section_heading(text):
        return "SECTION", 0.9, None

    if is_list_item(text, in_references=in_references) and not is_likely_heading_not_list(
        text, block, in_body=in_body
    ):
        return "LIST_ITEM", 0.84, None

    if block.classification == "REFERENCE_TEXT" and not _is_author_bio(text):
        return "REFERENCE", 0.84, None

    if is_standalone_equation_text(text) and not is_explanatory_math_context(text):
        return "EQUATION_FRAGMENT", 0.8, "standalone_equation"

    if is_math_fragment(text) and not is_explanatory_math_context(text):
        return "EQUATION_FRAGMENT", 0.78, None

    if len(text) > 25 and block.classification in {"PARAGRAPH", "BODY_TEXT"}:
        return "PARAGRAPH", 0.82, None

    if text and len(text) <= 25 and block_height(block) < 15:
        if is_math_fragment(text):
            return "EQUATION_FRAGMENT", 0.72, None
        if re.fullmatch(r"[A-Z]", text):
            return "LAYOUT_OBJECT", 0.85, "stray_glyph"
        return "UNKNOWN_TEXT", 0.4, "short_unclassified_fragment"

    if text:
        return "UNKNOWN_TEXT", 0.38, "low_confidence_classification"

    return "UNKNOWN_TEXT", 0.25, "empty_text_block"
