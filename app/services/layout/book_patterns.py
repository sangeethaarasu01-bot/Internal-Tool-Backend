"""Book chapter and front/back matter heading patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.layout.semantic_patterns import first_line, normalize_text

SPELLED_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

BOOK_CHAPTER_NUMERIC_RE = re.compile(
    r"^(?:CHAPTER|Chapter)\s+(\d+)\s*[:\-.]?\s*(.+)$",
    re.IGNORECASE,
)
BOOK_INTERMISSION_RE = re.compile(
    r"^(?:INTERMISSION|Intermission)\s+(\d+)\s*[:\-.]?\s*(.+)$",
    re.IGNORECASE,
)
BOOK_SPECIAL_HEADING_RE = re.compile(
    r"^(Introduction|Preface|Acknowledgments?|About the Author|Conclusion|Index|Bibliography)$",
    re.IGNORECASE,
)
SPELLED_CHAPTER_RE = re.compile(
    r"^(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE)\s+(.+?)"
    r"(?:\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2})?\s*$",
    re.IGNORECASE,
)
INLINE_PAREN_CITATION_RE = re.compile(
    r"^\s*\([^)]{0,120}\d{4}[^)]{0,120}\)\s*\.?$"
)
BOOK_BIBLIO_AUTHOR_YEAR_RE = re.compile(
    r"^[A-Z][A-Za-z'\-]+,\s+(?:[A-Z]\.?\s*){1,4}\s*\(\d{4}[a-z]?\)",
)
BOOK_BIBLIO_AUTHOR_INITIAL_RE = re.compile(
    r"^[A-Z][A-Za-z'\-]+,\s+(?:[A-Z]\.?\s*){1,4}",
)


@dataclass(frozen=True)
class BookSectionHeading:
    heading: str
    level: int = 1
    chapter_number: int | None = None


def parse_book_section_heading(text: str) -> BookSectionHeading | None:
    """Detect book chapter / intermission / special section headings."""
    line = normalize_text(first_line(text))
    if not line or len(line) > 160:
        return None

    match = BOOK_CHAPTER_NUMERIC_RE.match(line)
    if match:
        number = int(match.group(1))
        title = match.group(2).strip()
        return BookSectionHeading(
            heading=f"Chapter {number}: {title}",
            level=1,
            chapter_number=number,
        )

    match = BOOK_INTERMISSION_RE.match(line)
    if match:
        number = int(match.group(1))
        title = match.group(2).strip()
        return BookSectionHeading(
            heading=f"Intermission {number}: {title}",
            level=1,
            chapter_number=None,
        )

    match = SPELLED_CHAPTER_RE.match(line)
    if match:
        spelled = match.group(1).lower()
        title = match.group(2).strip()
        number = SPELLED_NUMBERS.get(spelled)
        label = f"Chapter {number}: {title}" if number else f"{match.group(1).title()} {title}"
        return BookSectionHeading(heading=label, level=1, chapter_number=number)

    if BOOK_SPECIAL_HEADING_RE.match(line):
        return BookSectionHeading(heading=line, level=1)

    return None


def looks_like_book_chapter_reference_line(text: str) -> bool:
    """True for end-of-chapter bibliography lines, not inline (Author, Year) citations."""
    normalized = normalize_text(text).strip()
    if not normalized or normalized.upper() == "REFERENCES":
        return False
    if len(normalized) < 20:
        return False
    if INLINE_PAREN_CITATION_RE.match(normalized):
        return False
    if normalized.startswith("(") and ")" in normalized[:40] and len(normalized.split()) <= 12:
        return False
    if BOOK_BIBLIO_AUTHOR_YEAR_RE.match(normalized):
        return len(normalized.split()) >= 5
    if BOOK_BIBLIO_AUTHOR_INITIAL_RE.match(normalized):
        if re.search(r"\b(19|20)\d{2}\b", normalized) and len(normalized.split()) >= 6:
            return True
        if re.search(r"\.\s+[A-Z]", normalized) and len(normalized) >= 35:
            return True
    return False
