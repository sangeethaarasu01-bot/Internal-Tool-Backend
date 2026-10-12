"""Copyright-page legal notice lines (British Library, LoC CIP, etc.)."""

from __future__ import annotations

import re

from app.models.extraction import ExtractionResult, TextBlock
from app.pipeline.phase1.text_fidelity import join_ordered_block_text
from app.services.layout.reading_order import order_document_blocks
from app.services.layout.semantic_patterns import first_line, normalize_text

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


def fix_glued_copyright_lines(text: str) -> str:
    """Insert breaks/spaces where imprint lines were concatenated without whitespace."""
    if not text:
        return ""
    cleaned = _GLUE_AVAILABLE_LCC_RE.sub(r"\1\n\2", text)
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    return cleaned


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


def _imprint_scan_pages(raw: ExtractionResult, max_page: int = 12) -> list[tuple[TextBlock, int]]:
    items: list[tuple[TextBlock, int]] = []
    for block, page_number in order_document_blocks(raw.pages):
        if page_number > max_page:
            continue
        text = normalize_text(block.text or "")
        if text:
            items.append((block, page_number))
    return items


def extract_copyright_legal_notices(raw: ExtractionResult) -> list[dict[str, object]]:
    """
    Return legal-notice payloads for DocBook ``<info>/<legalnotice>``.

    Each item: ``{"role": "CIP"|None, "text": str, "bold": bool}``.
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

    for block, _page_number in _imprint_scan_pages(raw):
        for line in fix_glued_copyright_lines(block.text or "").splitlines():
            line = normalize_text(line).strip()
            if not line:
                continue
            if BRITISH_LIBRARY_LINE_RE.match(line):
                add_notice(line, role="CIP", bold=False)
            elif LCC_HEADING_LINE_RE.match(line):
                add_notice(line, role="CIP", bold=_block_line_is_bold(block, line))
            elif ALL_RIGHTS_RESERVED_RE.match(line) and len(line) < 400:
                add_notice(line, role=None, bold=False)
            elif PRINTED_IN_USA_RE.match(line):
                add_notice(line, role=None, bold=False)
            elif ANSI_PAPER_RE.search(line) and len(line) < 320:
                add_notice(line, role=None, bold=False)

    if notices:
        return notices

    blob = fix_glued_copyright_lines(join_ordered_block_text(raw, page_number=None))
    for line in blob.splitlines():
        line = normalize_text(line).strip()
        if BRITISH_LIBRARY_LINE_RE.match(line):
            add_notice(line, role="CIP", bold=False)
        elif LCC_HEADING_LINE_RE.match(line):
            add_notice(line, role="CIP", bold=True)
    return notices
