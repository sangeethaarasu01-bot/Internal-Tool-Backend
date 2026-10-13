"""Spec step 02 — PDF preflight before extraction is queued (no Redis)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from app.config import settings
from app.services.text_extractor import PdfValidationError


@dataclass
class JobPreflightReport:
    """Lightweight preflight stored on the extraction MongoDB document."""

    passed: bool
    page_count: int = 0
    encrypted: bool = False
    file_size_bytes: int = 0
    text_sample_chars: int = 0
    likely_scanned: bool = False
    column_layout_hint: str | None = None
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sample_text_chars(doc: pymupdf.Document, max_pages: int = 5) -> int:
    total = 0
    for i in range(min(doc.page_count, max_pages)):
        total += len((doc[i].get_text("text") or "").strip())
    return total


def run_pdf_preflight(file_path: str | Path, *, file_size_bytes: int) -> JobPreflightReport:
    """
    Validate PDF integrity and capture metadata for job intake.

    Raises ``PdfValidationError`` when the file cannot be processed at all.
    """
    path = Path(file_path)
    if not path.is_file():
        raise PdfValidationError(f"File not found: {path.name}")

    issues: list[str] = []
    warnings: list[str] = []

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise PdfValidationError(f"Could not open PDF: {exc}") from exc

    try:
        encrypted = bool(doc.is_encrypted)
        page_count = int(doc.page_count)
        if encrypted:
            issues.append("PDF is encrypted; decryption is not supported.")
        if page_count < 1:
            issues.append("PDF has no pages.")

        text_sample = _sample_text_chars(doc) if page_count else 0
        likely_scanned = page_count > 0 and text_sample < max(80, page_count)

        if page_count > settings.MAX_PDF_PAGES:
            warnings.append(
                f"PDF has {page_count} pages (recommended cap for legacy agent path is "
                f"{settings.MAX_PDF_PAGES}); extraction pipeline still runs for large books."
            )
        if likely_scanned and text_sample < 200:
            warnings.append(
                "Little extractable text in the first pages; document may be scanned — OCR may be required."
            )

        passed = not issues
        return JobPreflightReport(
            passed=passed,
            page_count=page_count,
            encrypted=encrypted,
            file_size_bytes=file_size_bytes,
            text_sample_chars=text_sample,
            likely_scanned=likely_scanned,
            column_layout_hint=None,
            issues=issues,
            warnings=warnings,
        )
    finally:
        doc.close()
