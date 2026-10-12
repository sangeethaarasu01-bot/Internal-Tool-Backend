"""Extract author biography from back-matter \"About the Author\" sections."""

from __future__ import annotations

import re

from app.models.extraction import ExtractionResult, TextBlock
from app.models.ir_schema import IRInlineMathElement, IRTextElement
from app.pipeline.phase1.text_fidelity import join_ordered_block_text
from app.services.layout.reading_order import order_document_blocks
from app.services.layout.semantic_patterns import first_line, normalize_text
from app.utils.book_blurb_text import clean_personblurb_text
from app.utils.span_inline import inline_elements_from_text_block

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


def _about_author_tail_blocks(raw: ExtractionResult, max_pages: int = 35) -> list[TextBlock]:
    if not raw.pages:
        return []
    pages = sorted(raw.pages, key=lambda p: p.page_number)
    tail_numbers = {page.page_number for page in pages[-max_pages:]}
    started = False
    collected: list[TextBlock] = []
    for block, page_number in order_document_blocks(raw.pages):
        if page_number not in tail_numbers:
            continue
        text = normalize_text(block.text or "")
        if not text:
            continue
        if not started:
            if ABOUT_AUTHOR_HEADING_RE.match(first_line(text)):
                started = True
                remainder = text.split("\n", 1)
                if len(remainder) > 1 and remainder[1].strip():
                    collected.append(block.model_copy(update={"text": remainder[1].strip()}))
                continue
            continue
        if ABOUT_AUTHOR_HEADING_RE.match(first_line(text)) or SECTION_BREAK_RE.match(first_line(text)):
            break
        if len(first_line(text)) < 80 and first_line(text).isupper():
            break
        collected.append(block)
    return collected


def extract_about_the_author_blurb_inline_elements(
    raw: ExtractionResult,
) -> list[IRTextElement | IRInlineMathElement]:
    blocks = _about_author_tail_blocks(raw)
    if not blocks:
        return []
    combined: list[IRTextElement | IRInlineMathElement] = []
    for block in blocks:
        combined.extend(inline_elements_from_text_block(block))
    if not combined:
        return []
    merged: list[IRTextElement | IRInlineMathElement] = []
    for element in combined:
        if not merged:
            merged.append(element)
            continue
        prev = merged[-1]
        if (
            isinstance(prev, IRTextElement)
            and isinstance(element, IRTextElement)
            and prev.bold == element.bold
            and prev.italic == element.italic
            and prev.superscript == element.superscript
            and prev.subscript == element.subscript
        ):
            merged[-1] = prev.model_copy(update={"value": prev.value + element.value})
        else:
            merged.append(element)
    return merged


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


def serialize_author_blurb_inline_elements(
    elements: list[IRTextElement | IRInlineMathElement],
) -> list[dict]:
    payload: list[dict] = []
    for element in elements:
        if isinstance(element, IRInlineMathElement):
            payload.append(element.model_dump(mode="json"))
        else:
            payload.append(element.model_dump(mode="json"))
    return payload


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
