"""Typography normalization for DocBook book text (metadata, bios, and body)."""

from __future__ import annotations

import re

from app.utils.text_utils import dehyphenate_line_breaks
_TRAILING_PAGE_NUMBER_RE = re.compile(r"\.\s+\d{1,4}\s*$")
_TRAILING_PAGE_NUMBER_BEFORE_PERIOD_RE = re.compile(r"(\w)\s+\d{1,4}\s*\.?\s*$")
_INC_ABBREV_RE = re.compile(r"\bInc\b(?!\.)")
_STUCK_LOWER_THEN_UPPER_RE = re.compile(r"(?<=[a-zà-öø-ÿ])(?=[A-Z])")
_STUCK_CAPS_THEN_TITLECASE_RE = re.compile(r"([A-Z]{2,})([A-Z][a-z])")
_STUCK_PERIOD_BEFORE_DIGIT_RE = re.compile(r"(?<=[A-Za-z]\.)(?=\d)")
_STUCK_DIGIT_BEFORE_WEB_RE = re.compile(r"(?<=\d)(?=(?:www\.|https?://))", re.IGNORECASE)
_STUCK_LETTER_BEFORE_WEB_RE = re.compile(r"(?<=[a-z])(?=www\.)", re.IGNORECASE)
_STUCK_PERIOD_BEFORE_UPPER_RE = re.compile(r"(?<=\.)(?=[A-Z])")
_ADDRESS_UNIT_NUMBER_RE = re.compile(
    r"\b(?:Suite|Ste\.?|Apt\.?|Apartment|Unit|Floor|Fl\.?|Room|Rm\.?|#)\s+\d",
    re.IGNORECASE,
)


def _strip_trailing_page_numbers(text: str) -> str:
    """Drop footer page numbers; never treat Suite/Apt/Unit/Floor numbers as footers."""
    cleaned = _TRAILING_PAGE_NUMBER_RE.sub(".", text)
    if _ADDRESS_UNIT_NUMBER_RE.search(cleaned):
        return cleaned
    return _TRAILING_PAGE_NUMBER_BEFORE_PERIOD_RE.sub(r"\1.", cleaned)


def _curly_double_quotes(text: str) -> str:
    out: list[str] = []
    open_quote = True
    for char in text:
        if char == '"':
            out.append("\u201c" if open_quote else "\u201d")
            open_quote = not open_quote
        else:
            out.append(char)
    return "".join(out)


def repair_pdf_stuck_word_boundaries(text: str) -> str:
    """
    Insert missing spaces where PDF text runs were glued (no hardcoded titles).

    Examples: ``BOOKSLanham`` → ``BOOKS Lanham``, ``Inc.4501`` → ``Inc. 4501``,
    ``20706www`` → ``20706 www``.
    """
    if not text:
        return ""
    cleaned = text
    cleaned = _STUCK_LOWER_THEN_UPPER_RE.sub(" ", cleaned)
    cleaned = _STUCK_CAPS_THEN_TITLECASE_RE.sub(r"\1 \2", cleaned)
    cleaned = _STUCK_PERIOD_BEFORE_DIGIT_RE.sub(" ", cleaned)
    cleaned = _STUCK_PERIOD_BEFORE_UPPER_RE.sub(" ", cleaned)
    cleaned = _STUCK_DIGIT_BEFORE_WEB_RE.sub(" ", cleaned)
    cleaned = _STUCK_LETTER_BEFORE_WEB_RE.sub(" ", cleaned)
    return re.sub(r" {2,}", " ", cleaned)


def prepare_book_text_for_xml(text: str) -> str:
    """Typography first, then strip illegal XML characters (escaping happens at serialization)."""
    from app.utils.xml_text import sanitize_xml_text

    return sanitize_xml_text(apply_book_typography(text or ""))


def apply_book_typography(text: str) -> str:
    """
    Post-extraction cleanup: curly quotes/apostrophes, de-hyphenation, footer digits.
    """
    if not text:
        return ""
    cleaned = text.replace("\u00ad", "")
    cleaned = dehyphenate_line_breaks(cleaned)
    cleaned = repair_pdf_stuck_word_boundaries(cleaned)
    cleaned = _strip_trailing_page_numbers(cleaned)
    cleaned = cleaned.replace("\u2019", "'").replace("&#x27;", "'").replace("&#39;", "'")
    cleaned = cleaned.replace("'", "\u2019")
    cleaned = _curly_double_quotes(cleaned.replace("\u201c", '"').replace("\u201d", '"'))
    cleaned = _INC_ABBREV_RE.sub("Inc.", cleaned)
    cleaned = re.sub(r"[\n\r\t\f\v]+", " ", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()
