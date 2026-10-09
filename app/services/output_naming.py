"""Derive output filenames from the current job — never from unrelated DOIs."""

from __future__ import annotations

import re
from pathlib import Path


def safe_output_xml_filename(
    *,
    extraction_id: str,
    original_pdf_filename: str | None,
) -> str:
    stem = Path(original_pdf_filename or "document.pdf").stem
    stem = re.sub(r"[^\w.\-]+", "_", stem).strip("._") or "document"
    short_id = re.sub(r"[^\w]", "", extraction_id)[:12]
    return f"{stem}_{short_id}.xml"
