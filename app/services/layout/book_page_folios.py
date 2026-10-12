"""Map PDF page indices to printed folio labels for DocBook ``<?page?>`` PIs."""

from __future__ import annotations

import re

from app.models.extraction import ExtractionResult
from app.services.layout.text_filter import _near_bottom, _near_top
from app.utils.book_running_headers import is_book_running_header_text

_ROMAN_FOLIO_RE = re.compile(r"^[ivxlcdmIVXLCDM]{1,6}$")
_ARABIC_FOLIO_RE = re.compile(r"^\d{1,4}$")
_FOLIO_PREFIX_RE = re.compile(r"^(\d{1,4})\s+")


def _normalize_margin_line(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split()).strip()


def _folio_from_margin_line(line: str) -> str | None:
    flat = _normalize_margin_line(line)
    if not flat:
        return None
    if _ROMAN_FOLIO_RE.match(flat):
        return flat.lower()
    if _ARABIC_FOLIO_RE.match(flat):
        return flat
    match = _FOLIO_PREFIX_RE.match(flat)
    if match and is_book_running_header_text(flat):
        return match.group(1)
    return None


def build_book_page_folio_map(raw: ExtractionResult) -> dict[str, str]:
    """
    For each PDF page, best printed folio from margin blocks (roman, arabic, or folio+title).
    Keys are stringified PDF page numbers for JSON storage.
    """
    folios: dict[str, str] = {}
    for page in raw.pages:
        page_number = page.page_number
        height = page.height
        candidate: str | None = None
        for block in page.blocks:
            if block.type != "text":
                continue
            text = block.text or ""
            y0, y1 = block.bbox[1], block.bbox[3]
            if not (_near_top(y0, height) or _near_bottom(y0, y1, height)):
                continue
            for line in text.splitlines():
                folio = _folio_from_margin_line(line)
                if folio:
                    candidate = folio
        if candidate:
            folios[str(page_number)] = candidate
    return folios


def folio_label_for_pdf_page(folio_map: dict[str, str] | None, pdf_page: int | None) -> str | None:
    if pdf_page is None or not folio_map:
        return None
    return folio_map.get(str(pdf_page))
