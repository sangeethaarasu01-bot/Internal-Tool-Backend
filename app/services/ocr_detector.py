"""Heuristic OCR-need detection. Stage 1 does not run OCR."""

from __future__ import annotations

LOW_TEXT_CHAR_THRESHOLD = 50


def page_requires_ocr(text_char_count: int) -> bool:
    return text_char_count < LOW_TEXT_CHAR_THRESHOLD


def document_requires_ocr(page_char_counts: list[int]) -> bool:
    """True when the document is mostly empty/image-based pages."""
    if not page_char_counts:
        return True
    low_pages = sum(1 for count in page_char_counts if page_requires_ocr(count))
    return (low_pages / len(page_char_counts)) >= 0.5


def classify_pages(page_char_counts: list[int]) -> tuple[list[int], list[int]]:
    """Return (pages_with_low_text, pages_with_no_text) using 1-based page numbers."""
    low: list[int] = []
    empty: list[int] = []
    for index, count in enumerate(page_char_counts, start=1):
        if count <= 0:
            empty.append(index)
        elif page_requires_ocr(count):
            low.append(index)
    return low, empty
