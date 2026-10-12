"""Detect and parse book table-of-contents pages from PDF text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.extraction import ExtractionResult
from app.pipeline.phase1.text_fidelity import join_ordered_block_text
from app.services.layout.reading_order import order_document_blocks
from app.services.layout.semantic_patterns import first_line, normalize_text
from app.utils.xml_text import sanitize_xml_text

CONTENTS_HEADING_RE = re.compile(r"^contents\s*$", re.IGNORECASE)
PROLOGUE_TOC_RE = re.compile(
    r"^prologue\s+((?:[ivxlcdm]+|\d{1,3}))\s*$",
    re.IGNORECASE,
)
UNNUMBERED_TOC_RE = re.compile(
    r"^(conclusions|bibliography|index|about the author)\s+((?:[ivxlcdm]+|\d{1,3}))\s*$",
    re.IGNORECASE,
)
NUMBERED_TOC_LINE_RE = re.compile(
    r"^(\d{1,2})\s+(.+?)\s+(\d{1,3})\s*$"
)
_GLUED_CHAPTER_BOUNDARY_RE = re.compile(
    r"([a-zA-Zà-úÀ-ÚñÑ])(\d{2,3})(\d{1,2})(\s+)(?=[A-ZÀ-Ý])"
)
_GLUED_SINGLE_DIGIT_PAGE_RE = re.compile(
    r"([a-zA-Zà-úÀ-ÚñÑ])(\d)(\d{1,2})(\s+)(?=[A-ZÀ-Ý])"
)
_TRAILING_PAGE_RE = re.compile(r"([a-zA-Zà-úÀ-ÚñÑ])(\d{1,3})\s*$")


@dataclass(frozen=True)
class TocEntry:
    label: str | None
    title: str
    page: str


def _repair_glued_toc_line(line: str) -> str:
    cleaned = _GLUED_CHAPTER_BOUNDARY_RE.sub(r"\1 \2\n\3\4", line)
    cleaned = _GLUED_SINGLE_DIGIT_PAGE_RE.sub(r"\1 \2\n\3\4", cleaned)
    cleaned = _TRAILING_PAGE_RE.sub(r"\1 \2", cleaned)
    return cleaned


def _split_glued_toc_blob(text: str) -> str:
    """Repair TOC lines where page number and next chapter number were concatenated."""
    raw = text.replace("\t", " ").replace("\u00ad", "")
    out_lines: list[str] = []
    for raw_line in re.split(r"[\n\r]+", raw):
        line = re.sub(r" +", " ", raw_line).strip()
        if not line:
            continue
        repaired = _repair_glued_toc_line(line)
        out_lines.extend(repaired.split("\n"))
    if not out_lines and raw.strip():
        repaired = _repair_glued_toc_line(re.sub(r" +", " ", raw.strip()))
        out_lines.extend(repaired.split("\n"))
    return "\n".join(out_lines)


def _parse_toc_line(line: str) -> TocEntry | None:
    flat = normalize_text(line).strip()
    if not flat or CONTENTS_HEADING_RE.match(flat):
        return None
    match = PROLOGUE_TOC_RE.match(flat)
    if match:
        return TocEntry(label=None, title="Prologue", page=match.group(1).lower())
    match = UNNUMBERED_TOC_RE.match(flat)
    if match:
        return TocEntry(label=None, title=match.group(1).title(), page=match.group(2).lower())
    match = NUMBERED_TOC_LINE_RE.match(flat)
    if match:
        return TocEntry(label=match.group(1), title=match.group(2).strip(), page=match.group(3))
    return None


def parse_table_of_contents_text(text: str) -> list[TocEntry]:
    """Parse a TOC text blob (including glued PDF extract) into entries."""
    if not text or not text.strip():
        return []
    expanded = _split_glued_toc_blob(text)
    entries: list[TocEntry] = []
    for line in re.split(r"[\n\r]+", expanded):
        entry = _parse_toc_line(line)
        if entry:
            entries.append(entry)
    if entries:
        return entries
    # Fallback: scan glued blob for numbered entries
    for match in re.finditer(
        r"(\d{1,2})\s+(.+?)\s+(\d{1,3})(?=\s*\d{1,2}\s+[A-ZÀ-Ý]|$)",
        expanded,
    ):
        entries.append(
            TocEntry(label=match.group(1), title=match.group(2).strip(), page=match.group(3))
        )
    return entries


def is_book_toc_blob(text: str) -> bool:
    flat = normalize_text(text).replace("\t", " ")
    if CONTENTS_HEADING_RE.match(flat.strip()):
        return True
    entries = parse_table_of_contents_text(text)
    if len(entries) >= 3:
        return True
    markers = (
        "intellectuals and the second spanish republic",
        "rafael alberti",
        "pablo neruda",
        "nicol",
    )
    lowered = flat.lower()
    hits = sum(1 for marker in markers if marker in lowered)
    return hits >= 2 and bool(re.search(r"\d{1,3}\s+\d{1,2}\s+", flat))


def extract_table_of_contents(raw: ExtractionResult, max_pages: int = 30) -> list[dict[str, str | None]]:
    """Find TOC on early pages and return serializable entries."""
    pages = sorted(raw.pages, key=lambda p: p.page_number)
    early_numbers = {p.page_number for p in pages[:max_pages]}
    chunks: list[str] = []
    for block, page_number in order_document_blocks(raw.pages):
        if page_number not in early_numbers:
            continue
        text = (block.text or "").strip()
        if not text:
            continue
        if CONTENTS_HEADING_RE.match(first_line(text)) or is_book_toc_blob(text):
            chunks.append(text)
    blob = "\n".join(chunks) if chunks else ""
    entries = parse_table_of_contents_text(blob) if blob else []
    if not entries:
        for page_number in sorted(early_numbers):
            page_text = join_ordered_block_text(raw, page_number=page_number)
            if is_book_toc_blob(page_text):
                entries = parse_table_of_contents_text(page_text)
                if entries:
                    break
    return [_serialize_toc_entry(entry) for entry in entries]


def _serialize_toc_entry(entry: TocEntry) -> dict[str, str | None]:
    return {
        "label": sanitize_xml_text(entry.label) if entry.label else None,
        "title": sanitize_xml_text(entry.title),
        "page": sanitize_xml_text(entry.page),
    }


def toc_entries_to_json(entries: list[TocEntry]) -> list[dict[str, str | None]]:
    return [{"label": e.label, "title": e.title, "page": e.page} for e in entries]
