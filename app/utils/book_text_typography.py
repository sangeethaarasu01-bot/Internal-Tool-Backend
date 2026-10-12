"""Typography normalization for DocBook book text (metadata, bios, and body)."""

from __future__ import annotations

import re

_HYPHEN_BREAK_RE = re.compile(r"(\w)-\s+(\w)")
_TRAILING_PAGE_NUMBER_RE = re.compile(r"\.\s+\d{1,4}\s*$")
_TRAILING_PAGE_NUMBER_BEFORE_PERIOD_RE = re.compile(r"(\w)\s+\d{1,4}\s*\.?\s*$")
_INC_ABBREV_RE = re.compile(r"\bInc\b(?!\.)")
_STUCK_WORD_BOUNDARY_RE = re.compile(r"(?<=[a-zà-öø-ÿ])(?=[A-Z])")
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
    cleaned = _HYPHEN_BREAK_RE.sub(r"\1\2", cleaned)
    cleaned = _STUCK_WORD_BOUNDARY_RE.sub(" ", cleaned)
    cleaned = _strip_trailing_page_numbers(cleaned)
    cleaned = cleaned.replace("\u2019", "'").replace("&#x27;", "'").replace("&#39;", "'")
    cleaned = cleaned.replace("'", "\u2019")
    cleaned = _curly_double_quotes(cleaned.replace("\u201c", '"').replace("\u201d", '"'))
    cleaned = _INC_ABBREV_RE.sub("Inc.", cleaned)
    return cleaned
