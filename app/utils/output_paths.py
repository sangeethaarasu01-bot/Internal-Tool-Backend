"""Output file naming helpers."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def xml_output_filename(pdf_filename: str, *, fallback_stem: str = "article") -> str:
    """Derive ``access-kakichi-3657695-proof.xml`` from the uploaded PDF name."""
    stem = Path(pdf_filename or "").stem.strip() or fallback_stem
    stem = _INVALID_FILENAME_CHARS.sub("_", stem).strip(" .")
    if not stem:
        stem = fallback_stem
    return f"{stem}.xml"
