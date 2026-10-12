"""Typography normalization for DocBook book text (metadata, bios, and body)."""

from __future__ import annotations

import re

_HYPHEN_BREAK_RE = re.compile(r"(\w)-\s+(\w)")
_TRAILING_PAGE_NUMBER_RE = re.compile(r"\.\s+\d{1,4}\s*$")
_TRAILING_PAGE_NUMBER_BEFORE_PERIOD_RE = re.compile(r"(\w)\s+\d{1,4}\s*\.?\s*$")
_INC_ABBREV_RE = re.compile(r"\bInc\b(?!\.)")


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


def apply_book_typography(text: str) -> str:
    """
    Post-extraction cleanup: curly quotes/apostrophes, de-hyphenation, footer digits.
    """
    if not text:
        return ""
    cleaned = text.replace("\u00ad", "")
    cleaned = _HYPHEN_BREAK_RE.sub(r"\1\2", cleaned)
    cleaned = _TRAILING_PAGE_NUMBER_RE.sub(".", cleaned)
    cleaned = _TRAILING_PAGE_NUMBER_BEFORE_PERIOD_RE.sub(r"\1.", cleaned)
    cleaned = cleaned.replace("\u2019", "'").replace("&#x27;", "'")
    cleaned = cleaned.replace("'", "\u2019")
    cleaned = _curly_double_quotes(cleaned.replace("\u201c", '"').replace("\u201d", '"'))
    cleaned = _INC_ABBREV_RE.sub("Inc.", cleaned)
    return cleaned
