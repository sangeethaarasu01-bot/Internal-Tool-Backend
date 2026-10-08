"""Classify PDFs as text-based, scanned/image-heavy, or mixed."""

from __future__ import annotations

from app.models.extraction import ExtractionResult
from app.models.extracted_document import PdfDocumentKind
from app.services.ocr_detector import page_requires_ocr

_IMAGE_BLOCK_RATIO_THRESHOLD = 0.35


def classify_pdf_document_kind(raw: ExtractionResult) -> PdfDocumentKind:
    pages = raw.pages
    if not pages:
        return "scanned_image_based"

    n = len(pages)
    strong_text_pages = sum(
        1 for page in pages if page.text_char_count >= 200 and not page.requires_ocr
    )
    empty_pages = len(raw.stats.pages_with_no_text)
    low_text_pages = len(raw.stats.pages_with_low_text)

    image_heavy_pages = 0
    for page in pages:
        text_blocks = sum(1 for block in page.blocks if block.type == "text" and (block.text or "").strip())
        image_blocks = sum(1 for block in page.blocks if block.type == "image")
        total = text_blocks + image_blocks
        if total and image_blocks / total >= _IMAGE_BLOCK_RATIO_THRESHOLD and page.text_char_count < 200:
            image_heavy_pages += 1

    if strong_text_pages >= max(1, int(n * 0.75)):
        return "text_based"

    if empty_pages + low_text_pages >= int(n * 0.5):
        if strong_text_pages > 0 or (n - empty_pages) > empty_pages:
            return "mixed"
        return "scanned_image_based"

    if image_heavy_pages >= int(n * 0.3) and strong_text_pages > 0:
        return "mixed"

    if raw.document.requires_ocr and strong_text_pages == 0:
        return "scanned_image_based"

    if strong_text_pages > 0:
        return "text_based" if strong_text_pages >= int(n * 0.5) else "mixed"

    return "unknown"


def quality_warnings(raw: ExtractionResult, kind: PdfDocumentKind) -> list[str]:
    warnings: list[str] = []
    if kind == "scanned_image_based":
        warnings.append(
            "PDF appears scanned or image-based; Stage 1 does not run OCR — text may be missing."
        )
    elif kind == "mixed":
        warnings.append(
            "PDF appears mixed (some pages lack extractable text); verify page-level output."
        )
    if raw.document.requires_ocr:
        warnings.append("Document flagged as requiring OCR for acceptable text coverage.")
    for page in raw.pages:
        if page_requires_ocr(page.text_char_count) and page.text_char_count > 0:
            warnings.append(
                f"Page {page.page_number} has very little extractable text ({page.text_char_count} chars)."
            )
            break
    return warnings
