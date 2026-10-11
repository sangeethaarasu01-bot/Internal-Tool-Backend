"""Detect book PDF running headers (folio + chapter) that are not body text."""

from __future__ import annotations

import re

BOOK_FOLIO_CHAPTER_HEADER_RE = re.compile(
    r"^(?P<page>\d{1,4})\s+"
    r"(?:Chapter|CHAPTER|Part|PART|Intermission|INTERMISSION)\s+"
    r"(?P<num>\d{1,3})"
    r"(?:\s*[:\-–—].*)?$",
    re.IGNORECASE,
)
BOOK_CHAPTER_HEADER_RE = re.compile(
    r"^(?:Chapter|CHAPTER|Part|PART|Intermission|INTERMISSION)\s+"
    r"\d{1,3}(?:\s*[:\-–—].*)?$",
    re.IGNORECASE,
)


def is_book_folio_chapter_running_header(text: str) -> bool:
    flat = " ".join((text or "").replace("\n", " ").split()).strip()
    return bool(flat) and bool(BOOK_FOLIO_CHAPTER_HEADER_RE.match(flat))


def is_book_running_header_text(text: str) -> bool:
    flat = " ".join((text or "").replace("\n", " ").split()).strip()
    if not flat or len(flat) > 120:
        return False
    if is_book_folio_chapter_running_header(flat):
        return True
    if BOOK_CHAPTER_HEADER_RE.match(flat) and len(flat.split()) <= 6:
        return True
    return False
