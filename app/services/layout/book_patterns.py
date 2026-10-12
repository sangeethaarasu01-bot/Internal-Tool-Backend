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
BOOK_NUMBERED_CHAPTER_LINE_RE = re.compile(r"^(\d{1,2})\s+(.+)$")
BOOK_BACK_MATTER_HEADINGS = frozenset(
    {
        "index",
        "about the author",
        "about the authors",
        "bibliography",
        "references",
        "works cited",
        "colophon",
    }
)
_IMPRINT_FRAGMENT_RE = re.compile(
    r"(published by|all rights reserved|library of congress|cataloging-in-publication|"
    r"lexington books|rowman\s*&\s*littlefield|www\.rowman)",
    re.IGNORECASE,
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


def is_book_back_matter_heading(heading: str) -> bool:
    return normalize_text(heading).strip().lower() in BOOK_BACK_MATTER_HEADINGS


def _is_duplicate_front_title(
    line: str,
    book_title: str | None,
    book_subtitle: str | None,
) -> bool:
    candidate = normalize_text(line).strip().lower()
    if not candidate:
        return True
    for reference in (book_title, book_subtitle):
        if not reference:
            continue
        ref = normalize_text(reference).strip().lower()
        if not ref:
            continue
        if candidate == ref:
            return True
        if len(candidate) > 20 and (candidate in ref or ref in candidate):
            return True
    return False


def parse_book_title_block_heading(
    text: str,
    *,
    book_title: str | None = None,
    book_subtitle: str | None = None,
) -> BookSectionHeading | None:
    """
    Map interior TITLE-classified PDF blocks to chapter / back-matter headings.

    Used after book front matter is captured so chapter display titles are not dropped.
    """
    parsed = parse_book_section_heading(text)
    if parsed:
        return parsed

    line = normalize_text(first_line(text))
    if not line or len(line) > 120:
        return None
    if _is_duplicate_front_title(line, book_title, book_subtitle):
        return None
    if _IMPRINT_FRAGMENT_RE.search(line):
        return None

    match = BOOK_NUMBERED_CHAPTER_LINE_RE.match(line)
    if match:
        title_part = match.group(2).strip()
        number = int(match.group(1))
        if (
            1 <= number <= 40
            and 8 <= len(title_part) <= 100
            and not title_part.endswith(".")
        ):
            return BookSectionHeading(
                heading=f"Chapter {number}: {title_part}",
                level=1,
                chapter_number=number,
            )

    if line.endswith(".") or len(line.split()) > 14:
        return None
    if len(line) < 12:
        return None
    if is_book_back_matter_heading(line):
        return BookSectionHeading(heading=line, level=1)
    if ":" in line or len(line.split()) >= 3:
        return BookSectionHeading(heading=line, level=1)
    return None


def reorder_book_body_sections(sections: list) -> list:
    """Place index / about-the-author / bibliography sections after main chapters."""
    main: list = []
    back: list = []
    for section in sections:
        heading = getattr(section, "heading", None) or ""
        if is_book_back_matter_heading(str(heading)):
            back.append(section)
        else:
            main.append(section)
    return main + back


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
