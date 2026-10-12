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
# e.g. "152\tIndex", "142 Bibliography"
BOOK_FOLIO_SECTION_HEADER_RE = re.compile(
    r"^\d{1,4}\s+(?:Index|Bibliography|Notes|Contents|Preface|Introduction)\s*\.?\s*$",
    re.IGNORECASE,
)
# e.g. "135 Nicolás Guillén" (folio + short title fragment)
BOOK_FOLIO_NAME_HEADER_RE = re.compile(
    r"^\d{1,4}\s+[A-ZÀ-ÖØ-Ý][\w\s.'\-–—,]{0,80}$",
    re.UNICODE,
)
# e.g. "Pablo Neruda103" (name glued to page number)
BOOK_NAME_GLUED_FOLIO_RE = re.compile(
    r"^[A-ZÀ-ÖØ-Ý][\w\s.'\-–—]{2,60}\d{1,4}\s*$",
    re.UNICODE,
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
    if BOOK_FOLIO_SECTION_HEADER_RE.match(flat):
        return True
    if BOOK_FOLIO_NAME_HEADER_RE.match(flat) and len(flat.split()) <= 8:
        return True
    if BOOK_NAME_GLUED_FOLIO_RE.match(flat) and len(flat) < 80:
        return True
    return False
