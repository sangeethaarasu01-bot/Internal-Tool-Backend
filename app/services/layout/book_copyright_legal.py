"""Copyright-page legal notice lines (British Library, LoC CIP, etc.)."""

from __future__ import annotations

import re

from app.models.extraction import ExtractionResult, TextBlock
from app.pipeline.phase1.text_fidelity import join_ordered_block_text
from app.services.layout.reading_order import order_document_blocks
from app.services.layout.semantic_patterns import first_line, normalize_text
from app.utils.book_text_typography import repair_pdf_stuck_word_boundaries

BRITISH_LIBRARY_LINE_RE = re.compile(
    r"^British\s+Library\s+Cataloguing\s+in\s+Publication\s+Information\s+Available\.?\s*$",
    re.IGNORECASE,
)
LCC_HEADING_LINE_RE = re.compile(
    r"^Library\s+of\s+Congress\s+Cataloging-?in-?Publication\s+Data\.?\s*$",
    re.IGNORECASE,
)
ALL_RIGHTS_RESERVED_RE = re.compile(
    r"^.*\ball\s+rights\s+reserved\b.*$",
    re.IGNORECASE,
)
PRINTED_IN_USA_RE = re.compile(
    r"^Printed\s+in\s+the\s+United\s+States\b",
    re.IGNORECASE,
)
ANSI_PAPER_RE = re.compile(r"ANSI/NISO\s+Z39\.48", re.IGNORECASE)
_GLUE_AVAILABLE_LCC_RE = re.compile(
    r"(Publication\s+Information\s+Available)\s*(Library\s+of\s+Congress)",
    re.IGNORECASE,
)
_IMPRINT_LINE_BREAK_BEFORE_RE = re.compile(
    r"([^\n])(?=(?:Published by|An imprint of|Copyright|Unit [A-Z]|"
    r"British Library|Library of Congress|ISBN \d|The paper used|Printed in)\b)",
    re.IGNORECASE,
)


def fix_glued_copyright_lines(text: str) -> str:
    """Insert breaks/spaces where imprint lines were concatenated without whitespace."""
    if not text:
        return ""
    cleaned = repair_pdf_stuck_word_boundaries(text)
    cleaned = _GLUE_AVAILABLE_LCC_RE.sub(r"\1\n\2", cleaned)
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    return cleaned


def split_imprint_glued_text(text: str) -> list[str]:
    """Split one glued imprint block into top-to-bottom lines (reading order)."""
    repaired = fix_glued_copyright_lines(text or "")
    repaired = _IMPRINT_LINE_BREAK_BEFORE_RE.sub(r"\1\n", repaired)
    lines: list[str] = []
    for raw_line in repaired.splitlines():
        line = normalize_text(raw_line).strip()
        if line:
            lines.append(line)
    if not lines and repaired.strip():
        lines.append(normalize_text(repaired).strip())
    return lines


def is_book_imprint_block_text(text: str) -> bool:
    """True when a text block is clearly copyright/imprint page content (not body)."""
    flat = normalize_text(text)
    if len(flat) < 60:
        return False
    lowered = flat.lower()
    markers = (
        "published by",
        "copyright",
        "isbn",
        "all rights reserved",
        "www.",
        "an imprint of",
        "library of congress",
        "british library",
    )
    return sum(1 for marker in markers if marker in lowered) >= 3


def is_book_copyright_boilerplate_line(text: str) -> bool:
    line = normalize_text(first_line(text))
    if not line:
        return False
    if BRITISH_LIBRARY_LINE_RE.match(line):
        return True
    if LCC_HEADING_LINE_RE.match(line):
        return True
    if ALL_RIGHTS_RESERVED_RE.match(line) and len(line) < 400:
        return True
    if PRINTED_IN_USA_RE.match(line):
        return True
    if ANSI_PAPER_RE.search(line) and len(line) < 320:
        return True
    return False


def _block_line_is_bold(block: TextBlock, line: str) -> bool:
    target = normalize_text(line).strip()
    if not target:
        return False
    for text_line in block.lines:
        line_text = normalize_text(text_line.text or "").strip()
        if not line_text or target not in line_text:
            continue
        for span in text_line.spans:
            if not span.text:
                continue
            if target in normalize_text(span.text) and (span.flags & 16):
                return True
    return False


def _page_imprint_text(page) -> str:
    return " ".join((block.text or "") for block in page.blocks if (block.text or "").strip())


def _page_is_imprint(page, page_text: str) -> bool:
    from app.services.layout.book_metadata import (
        _page_is_copyright_imprint_page,
        _text_looks_like_publisher_imprint_page,
    )

    return _page_is_copyright_imprint_page(page) or _text_looks_like_publisher_imprint_page(page_text)


def _imprint_segments_from_block(block: TextBlock) -> list[str]:
    if block.lines and len(block.lines) > 1:
        segments: list[str] = []
        ordered = sorted(block.lines, key=lambda line: (line.bbox[1], line.bbox[0]))
        for text_line in ordered:
            segments.extend(split_imprint_glued_text(text_line.text or ""))
        if segments:
            return segments
    return split_imprint_glued_text(block.text or "")


def _notice_role_for_line(line: str) -> str | None:
    if BRITISH_LIBRARY_LINE_RE.match(line) or LCC_HEADING_LINE_RE.match(line):
        return "CIP"
    return None


def extract_copyright_legal_notices(raw: ExtractionResult) -> list[dict[str, object]]:
    """
    Return legal-notice payloads for DocBook ``<info>/<legalnotice>``.

    Each item: ``{"role": "CIP"|None, "text": str, "bold": bool}``.
    Imprint pages are walked in PDF page order (top to bottom).
    """
    notices: list[dict[str, object]] = []
    seen: set[str] = set()

    def add_notice(text: str, *, role: str | None, bold: bool) -> None:
        cleaned = normalize_text(text).strip()
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        notices.append({"role": role, "text": cleaned, "bold": bold})

    pages_by_number = {page.page_number: page for page in raw.pages}
    for page_number in sorted(pages_by_number):
        page = pages_by_number[page_number]
        page_text = _page_imprint_text(page)
        if not _page_is_imprint(page, page_text):
            continue
        for block, block_page in order_document_blocks(raw.pages):
            if block_page != page_number:
                continue
            block_text = normalize_text(block.text or "")
            if not block_text:
                continue
            for line in _imprint_segments_from_block(block):
                role = _notice_role_for_line(line)
                bold = bool(role == "CIP" and LCC_HEADING_LINE_RE.match(line))
                if bold:
                    bold = _block_line_is_bold(block, line)
                add_notice(line, role=role, bold=bold)

    if notices:
        return notices

    for block, _page_number in order_document_blocks(raw.pages):
        if _page_number > 12:
            continue
        for line in split_imprint_glued_text(block.text or ""):
            if is_book_copyright_boilerplate_line(line):
                role = _notice_role_for_line(line)
                add_notice(
                    line,
                    role=role,
                    bold=bool(role == "CIP" and LCC_HEADING_LINE_RE.match(line)),
                )

    if notices:
        return notices

    blob = split_imprint_glued_text(join_ordered_block_text(raw, page_number=None))
    for line in blob:
        if BRITISH_LIBRARY_LINE_RE.match(line):
            add_notice(line, role="CIP", bold=False)
        elif LCC_HEADING_LINE_RE.match(line):
            add_notice(line, role="CIP", bold=True)
    return notices
