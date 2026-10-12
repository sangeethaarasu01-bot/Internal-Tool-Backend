"""Classify removable boilerplate: footers, running headers, page numbers."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.models.document_structure import BlockClassification
from app.models.extraction import ExtractionResult, TextBlock
from app.services.layout.block_metrics import block_font_metrics
from app.services.layout.column_classifier import classify_block_column
from app.utils.book_running_headers import (
    is_book_folio_chapter_running_header,
    is_book_running_header_text,
)
from app.services.layout.semantic_patterns import (
    _CORRESPONDING_AUTHOR_NAME_RE,
    _IEEE_ET_AL_HEADER_RE,
    build_author_running_header_prefixes as derive_author_running_header_prefixes,
    DATE_HISTORY_RE,
    extract_ieee_et_al_header_prefix,
    extract_leading_roman_section_heading,
    IEEE_ACCESS_JOURNAL_HEADER_RE,
    IEEE_ACCESS_VOLUME_HEADER_RE,
    IEEE_LICENSE_FOOTER_RE,
    IEEE_PUBLICATION_HISTORY_RE,
    REFERENCE_LABEL_RE,
    matches_author_running_header_prefix,
    normalize_text,
    parse_author_names,
)

HEADER_Y_MAX = 50.0
FOOTER_Y_MARGIN = 40.0
TOP_MARGIN_RATIO = 0.11
BOTTOM_MARGIN_RATIO = 0.88
LEADING_PAGE_MARKER_RE = re.compile(
    r"^(?P<marker>\d{1,4}|[ivxlcdmIVXLCDM]{1,6})\s+(?P<body>.+)$"
)

FOOTER_PATTERN = re.compile(
    r"(©|copyright|all rights reserved|ieee\.org|publications/rights|"
    r"personal use is permitted|republication/redistribution|"
    r"the authors\.|licensed under a creative commons)",
    re.IGNORECASE,
)
RUNNING_HEADER_ACCESS = re.compile(
    r"^(?:\d+\s+)?IEEE\s+ACCESS(?:\s+\d+)?$",
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
PAGE_NUMBER_ONLY = re.compile(r"^\d{1,3}$")
ROMAN_NUMERAL_ONLY = re.compile(r"^[ivxlcdmIVXLCDM]{1,6}$")
FOLIO_WITH_SECTION_TITLE_RE = re.compile(
    r"^(?P<folio>[ivxlcdmIVXLCDM]{1,6})\s+(?P<title>[A-Za-z][\w\s\-–—':]{2,70})$"
)
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


def _near_top(y0: float, page_height: float) -> bool:
    return y0 < max(HEADER_Y_MAX, page_height * TOP_MARGIN_RATIO)


def _near_bottom(y0: float, y1: float, page_height: float) -> bool:
    center = (y0 + y1) / 2.0
    return y1 > page_height - FOOTER_Y_MARGIN or center > page_height * BOTTOM_MARGIN_RATIO


def _strip_leading_page_marker(flat: str) -> str:
    match = LEADING_PAGE_MARKER_RE.match(flat)
    if not match:
        return flat
    return match.group("body").strip()


def _register_margin_text(hits: dict[str, set[int]], flat: str, page_number: int) -> None:
    hits[flat].add(page_number)
    signature = _strip_leading_page_marker(flat)
    if signature != flat:
        hits[signature].add(page_number)


def _looks_like_running_author_header(flat: str) -> bool:
    if not flat or len(flat) > 200:
        return False
    if REFERENCE_LABEL_RE.match(normalize_text(flat)):
        return False
    if "," not in flat and not re.search(r"\band\b", flat, re.IGNORECASE):
        return False
    names = parse_author_names(flat)
    if names and len(names) >= 2:
        return True
    words = flat.split()
    return len(words) >= 4 and sum(1 for word in words if word[:1].isupper()) >= 3


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
            if not _near_top(y0, page.height):
                continue
            flat = _normalize_header_text(block.text)
            if flat:
                _register_margin_text(hits, flat, page.page_number)
    return hits


def collect_author_running_header_prefixes(result: ExtractionResult) -> list[str]:
    """Derive ordered IEEE running-header surname prefixes from page-1 metadata."""
    corresponding_name: str | None = None
    author_lines: list[str] = []
    for page in result.pages:
        if page.page_number != 1:
            continue
        for block in page.blocks:
            text = block.text or ""
            match = _CORRESPONDING_AUTHOR_NAME_RE.search(text)
            if match:
                corresponding_name = match.group(1).strip()
            y0 = block.bbox[1]
            if y0 < 260 and "," in text and "abstract" not in text.lower()[:12]:
                if parse_author_names(text):
                    author_lines.append(text)
    return derive_author_running_header_prefixes(
        result.pages,
        corresponding_name=corresponding_name,
        author_lines=author_lines,
    )


def build_running_footer_candidates(
    result: ExtractionResult,
) -> dict[str, set[int]]:
    """Map normalized bottom-band text -> page numbers where it appears."""
    hits: dict[str, set[int]] = defaultdict(set)
    for page in result.pages:
        for block in page.blocks:
            if block.type != "text" or not (block.text or "").strip():
                continue
            y1 = block.bbox[3]
            y0 = block.bbox[1]
            if not _near_bottom(y0, y1, page.height):
                continue
            flat = _normalize_header_text(block.text)
            if flat and len(flat) < 220:
                _register_margin_text(hits, flat, page.page_number)
    return hits


def _margin_furniture_line(flat: str) -> bool:
    """Short margin lines that are unlikely to be flowing body text."""
    if not flat or len(flat) > 160 or len(flat.split()) > 12:
        return False
    if REFERENCE_LABEL_RE.match(normalize_text(flat)):
        return False
    if ROMAN_NUMERAL_ONLY.match(flat):
        return True
    if FOLIO_WITH_SECTION_TITLE_RE.match(flat):
        return True
    stopwords = {"the", "and", "that", "which", "with", "from", "this", "have", "were", "for", "are"}
    words = flat.split()
    if len(words) <= 6 and flat[0].isupper() and flat.count(".") <= 1 and len(flat) < 55:
        if not any(word.lower() in stopwords for word in words[1:]):
            return True
    return False


def is_folio_margin_header(text: str, *, near_top: bool, near_bottom: bool) -> FilterDecision | None:
    flat = _normalize_header_text(text)
    if not flat or not (near_top or near_bottom):
        return None
    if ROMAN_NUMERAL_ONLY.match(flat):
        return FilterDecision(
            classification="PAGE_NUMBER",
            exclude_from_content=True,
            exclusion_reason="roman_folio_margin",
            confidence=0.88,
        )
    if near_top and FOLIO_WITH_SECTION_TITLE_RE.match(flat):
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="folio_section_running_header",
            confidence=0.9,
        )
    return None


def is_repeated_margin_furniture(
    text: str,
    *,
    near_top: bool,
    near_bottom: bool,
    page_number: int,
    running_header_pages: dict[str, set[int]],
    running_footer_pages: dict[str, set[int]] | None,
) -> FilterDecision | None:
    flat = _normalize_header_text(text)
    if not flat or not (near_top or near_bottom):
        return None
    if not _margin_furniture_line(flat):
        return None
    if near_top:
        for key in (flat, _strip_leading_page_marker(flat)):
            pages = running_header_pages.get(key, set())
            if len(pages) >= 2 and page_number in pages:
                return FilterDecision(
                    classification="RUNNING_HEADER",
                    exclude_from_content=True,
                    exclusion_reason="repeated_top_margin_furniture",
                    confidence=0.86,
                )
    if near_bottom and running_footer_pages:
        pages = running_footer_pages.get(flat, set())
        if len(pages) >= 2 and page_number in pages:
            return FilterDecision(
                classification="FOOTER",
                exclude_from_content=True,
                exclusion_reason="repeated_bottom_margin_furniture",
                confidence=0.86,
            )
    return None


def build_page_number_candidates(result: ExtractionResult) -> dict[str, set[int]]:
    """Map isolated page-number strings to pages where they appear near top/bottom."""
    hits: dict[str, set[int]] = defaultdict(set)
    for page in result.pages:
        for block in page.blocks:
            if block.type != "text":
                continue
            flat = _normalize_header_text(block.text)
            y0, y1 = block.bbox[1], block.bbox[3]
            near_edge = _near_top(y0, page.height) or _near_bottom(y0, y1, page.height)
            if not near_edge:
                continue
            if PAGE_NUMBER_ONLY.match(flat) or ROMAN_NUMERAL_ONLY.match(flat):
                hits[flat].add(page.page_number)
            elif RUNNING_HEADER_JOURNAL.match(flat):
                continue
            elif re.match(r"^\d+\s+IEEE", flat, re.I) or re.search(r"IEEE.*\s\d+$", flat, re.I):
                hits[flat].add(page.page_number)
    return hits


def is_footer_block(text: str, near_bottom: bool, near_top: bool = False) -> FilterDecision | None:
    flat = _normalize_header_text(text)
    if IEEE_LICENSE_FOOTER_RE.search(flat):
        return FilterDecision(
            classification="FOOTER",
            exclude_from_content=True,
            exclusion_reason="ieee_license_footer",
            confidence=0.96,
        )
    if not FOOTER_PATTERN.search(text):
        return None
    if not near_bottom and not near_top and "ieee.org" not in text.lower():
        return None
    return FilterDecision(
        classification="FOOTER",
        exclude_from_content=True,
        exclusion_reason="copyright_or_rights_pattern",
        confidence=0.95,
    )


def is_ieee_access_boilerplate(
    text: str,
    *,
    near_top: bool,
    near_bottom: bool,
    running_footer_pages: dict[str, set[int]] | None = None,
) -> FilterDecision | None:
    """IEEE Access / periodicals margin lines (volume, dates, license, page chrome)."""
    flat = _normalize_header_text(text)
    if not flat:
        return None

    if IEEE_ACCESS_VOLUME_HEADER_RE.match(flat) or RUNNING_HEADER_ACCESS.match(flat):
        if near_top or near_bottom:
            return FilterDecision(
                classification="RUNNING_HEADER",
                exclude_from_content=True,
                exclusion_reason="ieee_access_running_header",
                confidence=0.94,
            )

    if IEEE_ACCESS_JOURNAL_HEADER_RE.match(flat) and (near_top or near_bottom):
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="ieee_access_journal_header",
            confidence=0.94,
        )

    if DATE_HISTORY_RE.match(flat) or (
        IEEE_PUBLICATION_HISTORY_RE.search(flat) and len(flat) < 260
    ):
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="ieee_publication_history",
            confidence=0.93,
        )

    if running_footer_pages:
        pages = running_footer_pages.get(flat, set())
        if len(pages) >= 2 and (near_bottom or near_top) and len(flat) < 200:
            if IEEE_LICENSE_FOOTER_RE.search(flat) or FOOTER_PATTERN.search(flat):
                return FilterDecision(
                    classification="FOOTER",
                    exclude_from_content=True,
                    exclusion_reason="repeated_margin_footer",
                    confidence=0.9,
                )

    return None


def is_running_header_block(
    text: str,
    near_top: bool,
    running_header_pages: dict[str, set[int]],
    page_number: int,
    author_header_prefixes: list[str] | None = None,
) -> FilterDecision | None:
    if not near_top:
        return None
    flat = _normalize_header_text(text)
    if RUNNING_HEADER_JOURNAL.match(flat):
        pages = running_header_pages.get(flat, set())
        if len(pages) >= 2 or page_number > 1:
            return FilterDecision(
                classification="RUNNING_HEADER",
                exclude_from_content=True,
                exclusion_reason="repeated_top_journal_header",
                confidence=0.9,
            )
    et_al_prefix = extract_ieee_et_al_header_prefix(flat)
    if et_al_prefix and _IEEE_ET_AL_HEADER_RE.match(flat):
        if author_header_prefixes and matches_author_running_header_prefix(
            et_al_prefix, author_header_prefixes
        ):
            return FilterDecision(
                classification="RUNNING_HEADER",
                exclude_from_content=True,
                exclusion_reason="ieee_author_running_header",
                confidence=0.92,
            )
        if page_number > 1:
            return FilterDecision(
                classification="RUNNING_HEADER",
                exclude_from_content=True,
                exclusion_reason="ieee_author_running_header",
                confidence=0.88,
            )
    signature = _strip_leading_page_marker(flat)
    for key in (flat, signature):
        pages = running_header_pages.get(key, set())
        if len(pages) >= 2 and page_number in pages and _looks_like_running_author_header(
            signature
        ):
            return FilterDecision(
                classification="RUNNING_HEADER",
                exclude_from_content=True,
                exclusion_reason="repeated_author_running_header",
                confidence=0.88,
            )
    pages = running_header_pages.get(flat, set())
    if len(pages) >= 2 and len(flat) < 80 and _margin_furniture_line(flat):
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="repeated_top_text",
            confidence=0.8,
        )
    if len(pages) >= 3 and len(flat) < 80:
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="repeated_top_text",
            confidence=0.75,
        )
    return None


def is_leading_page_number_running_header(
    text: str,
    *,
    near_top: bool,
    page_number: int,
    running_header_pages: dict[str, set[int]],
) -> FilterDecision | None:
    if not near_top:
        return None
    flat = _normalize_header_text(text)
    body = _strip_leading_page_marker(flat)
    if body == flat or not _looks_like_running_author_header(body):
        return None
    pages = running_header_pages.get(body, set())
    if len(pages) >= 2 and page_number in pages:
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="repeated_author_running_header",
            confidence=0.9,
        )
    if page_number > 1 and len(pages) >= 1:
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="author_running_header_with_leading_page",
            confidence=0.86,
        )
    return None


def is_page_number_block(
    text: str,
    near_top: bool,
    near_bottom: bool,
    page_number_candidates: dict[str, set[int]],
    *,
    page_number: int,
) -> FilterDecision | None:
    flat = _normalize_header_text(text)
    if not (near_top or near_bottom):
        return None
    if PAGE_NUMBER_ONLY.match(flat):
        if near_bottom or len(page_number_candidates.get(flat, set())) >= 2 or (
            near_top and int(flat) > 1
        ):
            return FilterDecision(
                classification="PAGE_NUMBER",
                exclude_from_content=True,
                exclusion_reason="isolated_page_number_margin",
                confidence=0.85,
            )
    if ROMAN_NUMERAL_ONLY.match(flat) and (near_top or near_bottom):
        if near_bottom or page_number > 1 or len(page_number_candidates.get(flat, set())) >= 1:
            return FilterDecision(
                classification="PAGE_NUMBER",
                exclude_from_content=True,
                exclusion_reason="roman_folio_margin",
                confidence=0.84,
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
    author_header_prefixes: list[str] | None = None,
    running_footer_pages: dict[str, set[int]] | None = None,
    *,
    book_mode: bool = False,
) -> FilterDecision:
    text = (block.text or "").strip()
    if not text:
        return FilterDecision("UNKNOWN_TEXT", False, None, 0.3)

    if book_mode and page_number <= 15:
        from app.services.layout.book_copyright_legal import is_book_copyright_boilerplate_line

        if is_book_copyright_boilerplate_line(text):
            return FilterDecision(
                classification="UNKNOWN_TEXT",
                exclude_from_content=True,
                exclusion_reason="book_copyright_legal",
                confidence=0.94,
            )
        from app.services.layout.book_table_of_contents import is_book_toc_blob

        if is_book_toc_blob(text):
            return FilterDecision(
                classification="UNKNOWN_TEXT",
                exclude_from_content=True,
                exclusion_reason="book_table_of_contents",
                confidence=0.95,
            )

    y0, y1 = block.bbox[1], block.bbox[3]
    near_top = _near_top(y0, page_height)
    near_bottom = _near_bottom(y0, y1, page_height)

    boilerplate = is_ieee_access_boilerplate(
        text,
        near_top=near_top,
        near_bottom=near_bottom,
        running_footer_pages=running_footer_pages,
    )
    if boilerplate and not CITATION_PATTERN.search(text):
        return boilerplate

    footer = is_footer_block(text, near_bottom, near_top=near_top)
    if footer and not CITATION_PATTERN.search(text):
        return footer

    if (near_bottom or near_top) and re.fullmatch(r"[A-Z]", text):
        return FilterDecision(
            classification="FOOTER" if near_bottom else "RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="stray_page_glyph",
            confidence=0.9,
        )

    if in_references or REFERENCE_LABEL_RE.match(normalize_text(text)):
        return FilterDecision("REFERENCE_TEXT", False, None, 0.85)

    if (near_top or near_bottom) and is_book_folio_chapter_running_header(text):
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="book_folio_chapter_header",
            confidence=0.93,
        )
    if book_mode and near_top and is_book_running_header_text(text):
        return FilterDecision(
            classification="RUNNING_HEADER",
            exclude_from_content=True,
            exclusion_reason="book_chapter_running_header",
            confidence=0.9,
        )

    running = is_running_header_block(
        text,
        near_top,
        running_header_pages,
        page_number,
        author_header_prefixes,
    )
    if running:
        return running

    page_num = is_page_number_block(
        text,
        near_top,
        near_bottom,
        page_number_candidates,
        page_number=page_number,
    )
    if page_num:
        return page_num

    author_running = is_leading_page_number_running_header(
        text,
        near_top=near_top,
        page_number=page_number,
        running_header_pages=running_header_pages,
    )
    if author_running and not CITATION_PATTERN.search(text):
        return author_running

    folio = is_folio_margin_header(text, near_top=near_top, near_bottom=near_bottom)
    if folio and not CITATION_PATTERN.search(text):
        return folio

    repeated_margin = is_repeated_margin_furniture(
        text,
        near_top=near_top,
        near_bottom=near_bottom,
        page_number=page_number,
        running_header_pages=running_header_pages,
        running_footer_pages=running_footer_pages,
    )
    if repeated_margin and not CITATION_PATTERN.search(text):
        return repeated_margin

    _font, size, is_bold = block_font_metrics(block)
    flat = _normalize_header_text(text)
    col = classify_block_column(block, page_width)

    if TABLE_CAPTION_RE.match(flat):
        return FilterDecision("CAPTION", False, None, 0.85)

    section_kind = _classify_heading(
        text, flat, size, is_bold, body_font_size, col, book_mode=book_mode
    )
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
    *,
    book_mode: bool = False,
) -> str | None:
    if book_mode:
        from app.services.layout.book_patterns import parse_book_section_heading

        if parse_book_section_heading(text):
            return "SECTION"

    if extract_leading_roman_section_heading(text):
        return "SECTION"

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
