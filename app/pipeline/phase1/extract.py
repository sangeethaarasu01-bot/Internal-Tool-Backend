"""Public Phase 1 entry: PDF file → :class:`ExtractedDocument`."""

from __future__ import annotations

from pathlib import Path

from app.models.extracted_document import ExtractedDocument
from app.models.extraction import ExtractionResult
from app.pipeline.phase1.build_document import build_extracted_document
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.text_extractor import PdfValidationError, extract_text_layout


class Phase1ExtractionError(Exception):
    """Raised when Phase 1 extraction cannot proceed."""


def extract_pdf_document(
    pdf_path: str | Path,
    *,
    original_filename: str | None = None,
    include_full_layout: bool = False,
    bundle_dir: Path | None = None,
) -> tuple[ExtractedDocument, ExtractionResult]:
    """
    Run Phase 1 extraction only (no LLM).

    Returns the normalized :class:`ExtractedDocument` and the full
    :class:`ExtractionResult` (with structure) for debugging.
    """
    path = Path(pdf_path)
    try:
        raw = extract_text_layout(str(path), original_filename=original_filename or path.name)
    except PdfValidationError as exc:
        raise Phase1ExtractionError(str(exc)) from exc

    full = build_full_extraction_result(raw, include_tagged_output=False)
    document = build_extracted_document(
        raw,
        structure=full.structure,
        pdf_path=path,
        bundle_dir=bundle_dir,
    )
    document.detailed_extraction_included = include_full_layout
    return document, full
