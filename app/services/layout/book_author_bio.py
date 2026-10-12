"""Extract author biography from back-matter \"About the Author\" sections."""

from __future__ import annotations

import re

from app.models.extraction import ExtractionResult
from app.pipeline.phase1.text_fidelity import join_ordered_block_text
from app.services.layout.semantic_patterns import normalize_text
from app.utils.book_blurb_text import clean_personblurb_text

ABOUT_AUTHOR_HEADING_RE = re.compile(
    r"^\s*about\s+the\s+author(s)?\s*$",
    re.IGNORECASE,
)
SECTION_BREAK_RE = re.compile(
    r"^\s*(?:index|bibliography|references|appendix|notes|acknowledg)",
    re.IGNORECASE,
)
BIO_OPENER_NAME_RE = re.compile(
    r"^(.+?)\s+is\s+(?:an?|the)\s+",
    re.IGNORECASE,
)


def _back_matter_text(raw: ExtractionResult, max_pages: int = 35) -> str:
    if not raw.pages:
        return ""
    pages = sorted(raw.pages, key=lambda p: p.page_number)
    tail = pages[-max_pages:]
    return "\n".join(join_ordered_block_text(raw, page_number=page.page_number) for page in tail)


def extract_about_the_author_blurb(raw: ExtractionResult) -> str | None:
    """Return paragraph text following an About the Author heading, if present."""
    blob = _back_matter_text(raw)
    if not blob.strip():
        return None

    lines = [line.strip() for line in blob.splitlines()]
    start_index: int | None = None
    for index, line in enumerate(lines):
        if ABOUT_AUTHOR_HEADING_RE.match(line):
            start_index = index + 1
            break
    if start_index is None:
        return None

    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines[start_index:]:
        if not line:
            if buffer:
                paragraphs.append(" ".join(buffer))
                buffer = []
            continue
        if ABOUT_AUTHOR_HEADING_RE.match(line) or SECTION_BREAK_RE.match(line):
            break
        if len(line) < 80 and line.isupper():
            break
        buffer.append(line)
    if buffer:
        paragraphs.append(" ".join(buffer))

    text = normalize_text("\n\n".join(paragraphs)).strip()
    text = clean_personblurb_text(text)
    if len(text) < 40:
        return None
    return text


def extract_author_name_from_blurb_text(blurb: str) -> str | None:
    """Authoritative author name from the first sentence of a personblurb."""
    cleaned = clean_personblurb_text(blurb.strip())
    if not cleaned:
        return None
    match = BIO_OPENER_NAME_RE.match(cleaned)
    if not match:
        return None
    candidate = normalize_text(match.group(1)).strip().rstrip(".,;")
    if not candidate or len(candidate) > 80:
        return None
    return candidate


def extract_author_name_from_about_blurb(raw: ExtractionResult) -> str | None:
    """
    Parse the author name from the opening of the About the Author blurb.

    Example: ``Grant D. Moss is an Associate Professor...`` → ``Grant D. Moss``.
    """
    blurb = extract_about_the_author_blurb(raw)
    return extract_author_name_from_blurb_text(blurb or "")
