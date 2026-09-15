"""Classify removable boilerplate: footers, running headers, page numbers."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.models.document_structure import BlockClassification
from app.models.extraction import ExtractionResult, TextBlock
from app.services.layout.block_metrics import block_font_metrics
from app.services.layout.column_classifier import classify_block_column

HEADER_Y_MAX = 50.0
FOOTER_Y_MARGIN = 40.0

FOOTER_PATTERN = re.compile(
    r"(©|copyright|all rights reserved|ieee\.org|publications/rights|"
    r"personal use is permitted|republication/redistribution)",
    re.IGNORECASE,
)
CITATION_PATTERN = re.compile(
    r"(?:\[\d+\]|doi:\s*10\.|vol\.\s*\d+|pp\.\s*\d{2,})",
    re.IGNORECASE,
)
RUNNING_HEADER_JOURNAL = re.compile(
    r"^(?:\d+\s+)?IEEE\s+SENSORS\s+JOURNAL(?:\s+\d+)?$",
    re.IGNORECASE,
)
AUTHOR_RUNNING_HEADER = re.compile(
    r"MOULICK\s+et\s+al\.:.*CUSTOMIZED\s+e-TONGUE",
    re.IGNORECASE,
)
PAGE_NUMBER_ONLY = re.compile(r"^\d{1,3}$")
ROMAN_SECTION_RE = re.compile(
    r"^(?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.\s+[A-Z]",
    re.IGNORECASE,
)
LETTER_SUBSECTION_RE = re.compile(r"^[A-Z]\.\s+[A-Za-z]")
TABLE_CAPTION_RE = re.compile(r"^TABLE\s+[IVX\d]+", re.IGNORECASE)


@dataclass
class FilterDecision:
    classification: BlockClassification
    exclude_from_content: bool
    exclusion_reason: str | None
    confidence: float


def _normalize_header_text(text: str) -> str:
    return " ".join(text.replace("\n", " ").split()).strip()


def _near_top(y0: float) -> bool:
    return y0 < HEADER_Y_MAX


def _near_bottom(y1: float, page_height: float) -> bool:
    return y1 > page_height - FOOTER_Y_MARGIN


def build_running_header_candidates(
    result: ExtractionResult,
) -> dict[str, set[int]]:
    """Map normalized top-band text -> page numbers where it appears."""
    hits: dict[str, set[int]] = defaultdict(set)
    for page in result.pages:
        for block in page.blocks:
            if block.type != "text" or not (block.text or "").strip():
                continue
            y0 = block.bbox[1]
            if not _near_top(y0):
                continue
            flat = _normalize_header_text(block.text)
            if flat:
                hits[flat].add(page.page_number)
    return hits


def build_page_number_candidates(result: ExtractionResult) -> dict[str, set[int]]:
    """Map isolated page-number strings to pages where they appear near top/bottom."""
    hits: dict[str, set[int]] = defaultdict(set)
    for page in result.pages:
        for block in page.blocks:
            if block.type != "text":
                continue
            flat = _normalize_header_text(block.text)
            y0, y1 = block.bbox[1], block.bbox[3]
            near_edge = _near_top(y0) or _near_bottom(y1, page.height)
            if not near_edge:
                continue
            if PAGE_NUMBER_ONLY.match(flat):
                hits[flat].add(page.page_number)
            elif RUNNING_HEADER_JOURNAL.match(flat):
                continue
            elif re.match(r"^\d+\s+IEEE", flat, re.I) or re.search(r"IEEE.*\s\d+$", flat, re.I):
                hits[flat].add(page.page_number)
    return hits


def is_footer_block(text: str, near_bottom: bool) -> FilterDecision | None:
    if not FOOTER_PATTERN.search(text):
        return None
    if not near_bottom and "ieee.org" not in text.lower():
        return None
    return FilterDecision(
        classification="FOOTER",
        exclude_from_content=True,
        exclusion_reason="copyright_or_rights_pattern",
        confidence=0.95,
    )


def is_running_header_block(
    text: str,
    near_top: bool,
    running_header_pages: dict[str, set[int]],
    page_number: int,
) -> FilterDecision | None:
    if not near_top:
        return None
    flat = _normalize_header_text(text)
    if RUNNING_HEADER_JOURNAL.match(flat) or AUTHOR_RUNNING_HEADER.search(flat):
        pages = running_header_pages.get(flat, set())
        if len(pages) >= 2 or page_number > 1:
            return FilterDecision(
                classification="RUNNING_HEADER",
                exclude_from_content=True,
                exclusion_reason="repeated_top_journal_header",
                confidence=0.9,
            )
    pages = running_header_pages.get(flat, set())
    if len(pages) >= 3 and len(flat) < 80:
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="repeated_top_text",
            confidence=0.75,
        )
    return None


def is_page_number_block(
    text: str,
    near_top: bool,
    near_bottom: bool,
    page_number_candidates: dict[str, set[int]],
) -> FilterDecision | None:
    flat = _normalize_header_text(text)
    if not (near_top or near_bottom):
        return None
    if PAGE_NUMBER_ONLY.match(flat) and len(page_number_candidates.get(flat, set())) >= 2:
        return FilterDecision(
            classification="PAGE_NUMBER",
            exclude_from_content=True,
            exclusion_reason="isolated_repeated_page_number",
            confidence=0.85,
        )
    if RUNNING_HEADER_JOURNAL.match(flat):
        return None
    return None


def classify_content_block(
    block: TextBlock,
    page_number: int,
    page_width: float,
    page_height: float,
    in_references: bool,
    running_header_pages: dict[str, set[int]],
    page_number_candidates: dict[str, set[int]],
    body_font_size: float,
) -> FilterDecision:
    text = (block.text or "").strip()
    if not text:
        return FilterDecision("UNKNOWN_TEXT", False, None, 0.3)

    y0, y1 = block.bbox[1], block.bbox[3]
    near_top = _near_top(y0)
    near_bottom = _near_bottom(y1, page_height)

    footer = is_footer_block(text, near_bottom)
    if footer and not CITATION_PATTERN.search(text):
        return footer

    if in_references or CITATION_PATTERN.search(text):
        return FilterDecision("REFERENCE_TEXT", False, None, 0.85)

    running = is_running_header_block(text, near_top, running_header_pages, page_number)
    if running:
        return running

    page_num = is_page_number_block(text, near_top, near_bottom, page_number_candidates)
    if page_num:
        return page_num

    _font, size, is_bold = block_font_metrics(block)
    flat = _normalize_header_text(text)
    col = classify_block_column(block, page_width)

    if TABLE_CAPTION_RE.match(flat):
        return FilterDecision("CAPTION", False, None, 0.85)

    section_kind = _classify_heading(text, flat, size, is_bold, body_font_size, col)
    if section_kind == "SECTION":
        return FilterDecision("SECTION", False, None, 0.85)
    if section_kind == "SUBSECTION":
        return FilterDecision("SUBSECTION", False, None, 0.85)

    if len(text) > 20:
        return FilterDecision("PARAGRAPH", False, None, 0.7)

    if LETTER_SUBSECTION_RE.match(flat) and len(flat.split()) <= 10:
        return FilterDecision("SUBSECTION", False, None, 0.75)

    return FilterDecision("BODY_TEXT", False, None, 0.5)


def _classify_heading(
    text: str,
    flat: str,
    font_size: float | None,
    is_bold: bool,
    body_font_size: float,
    column: str,
) -> str | None:
    first = flat.split("\n", 1)[0].strip()
    if len(first) > 120 or len(first) < 4:
        return None
    if len(first.split()) > 14:
        return None

    if ROMAN_SECTION_RE.match(first):
        return "SECTION"

    if LETTER_SUBSECTION_RE.match(first):
        height_signal = len(first) <= 90
        style_signal = is_bold or (font_size and font_size >= body_font_size)
        if height_signal and (style_signal or len(first.split()) <= 8):
            return "SUBSECTION"

    if re.match(r"^\d+\.\d+", first) and len(first.split()) <= 12:
        return "SUBSECTION"

    return None
