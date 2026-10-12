"""Normalize author biography text extracted from PDFs."""

from __future__ import annotations

import re

from app.utils.book_text_typography import apply_book_typography


def clean_personblurb_text(text: str) -> str:
    """Normalize biography paragraphs after extraction."""
    if not text:
        return ""
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\u00ad", "")):
        chunk = apply_book_typography(" ".join(paragraph.split()))
        if chunk:
            paragraphs.append(chunk)
    return "\n\n".join(paragraphs).strip()
