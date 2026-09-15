"""Layout-aware digital PDF text extraction using PyMuPDF get_text('dict')."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.models.extraction import (
    DocumentInfo,
    DocumentMetadata,
    ExtractionResult,
    ExtractionStats,
    PageExtraction,
    TextBlock,
    TextLine,
    TextSpan,
)
from app.services.ocr_detector import (
    classify_pages,
    document_requires_ocr,
    page_requires_ocr,
)
from app.services.table_extractor import extract_tables_from_page

EXTRACTION_ENGINE = "pymupdf"
EXTRACTION_VERSION = "1.0.0"


class PdfValidationError(Exception):
    """Raised when a file is missing, not a PDF, or cannot be opened."""


def extract_text_layout(file_path: str, original_filename: str | None = None) -> ExtractionResult:
    path = Path(file_path)
    if not path.exists():
        raise PdfValidationError(f"File not found: {path.name}")
    _validate_pdf_header(path)

    try:
        doc = pymupdf.open(file_path)
    except Exception as exc:
        raise PdfValidationError(f"Could not open PDF: {exc}") from exc

    try:
        if doc.is_encrypted:
            raise PdfValidationError("Encrypted PDFs are not supported in Stage 1")
        if doc.page_count < 1:
            raise PdfValidationError("PDF has no pages")

        filename = original_filename or path.name
        pages: list[PageExtraction] = []
        ocr_applied = False
        for page_index in range(doc.page_count):
            page_result, page_ocr = _extract_page(doc[page_index], page_index + 1)
            pages.append(page_result)
            ocr_applied = ocr_applied or page_ocr

        char_counts = [page.text_char_count for page in pages]
        low_pages, empty_pages = classify_pages(char_counts)
        requires_ocr = document_requires_ocr(char_counts)

        stats = ExtractionStats(
            total_blocks=sum(len(page.blocks) for page in pages),
            total_lines=sum(len(block.lines) for page in pages for block in page.blocks),
            total_chars=sum(char_counts),
            pages_with_low_text=low_pages,
            pages_with_no_text=empty_pages,
        )
        metadata = _document_metadata(doc)
        document = DocumentInfo(
            filename=filename,
            page_count=doc.page_count,
            requires_ocr=requires_ocr,
            ocr_applied=ocr_applied,
            extraction_engine=EXTRACTION_ENGINE,
            extraction_version=EXTRACTION_VERSION,
            metadata=metadata,
        )
        return ExtractionResult(document=document, pages=pages, stats=stats)
    finally:
        doc.close()


def _validate_pdf_header(path: Path) -> None:
    size = path.stat().st_size
    if size == 0:
        raise PdfValidationError("PDF file is empty")
    with path.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        raise PdfValidationError("File is not a valid PDF")


def _document_metadata(doc: pymupdf.Document) -> DocumentMetadata:
    raw = doc.metadata or {}
    return DocumentMetadata(
        title=_clean_meta(raw.get("title")),
        author=_clean_meta(raw.get("author")),
        creator=_clean_meta(raw.get("creator")),
        producer=_clean_meta(raw.get("producer")),
        creation_date=_clean_meta(raw.get("creationDate")),
        modification_date=_clean_meta(raw.get("modDate")),
    )


def _clean_meta(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_page(page: pymupdf.Page, page_number: int) -> tuple[PageExtraction, bool]:
    payload = page.get_text("dict")
    width = float(payload.get("width") or page.rect.width)
    height = float(payload.get("height") or page.rect.height)
    blocks: list[TextBlock] = []

    for block_index, raw_block in enumerate(payload.get("blocks") or []):
        blocks.append(_extract_block(raw_block, page_number, block_index))

    tables, ocr_applied = extract_tables_from_page(page, page_number, blocks)
    text = "".join(block.text for block in blocks)
    char_count = len(text)
    return (
        PageExtraction(
            page_number=page_number,
            width=width,
            height=height,
            text_char_count=char_count,
            requires_ocr=page_requires_ocr(char_count),
            blocks=blocks,
            tables=tables,
        ),
        ocr_applied,
    )


def _extract_block(raw_block: dict, page_number: int, block_index: int) -> TextBlock:
    block_id = f"p{page_number}_b{block_index}"
    block_type = "image" if raw_block.get("type") == 1 else "text"
    bbox = _bbox(raw_block.get("bbox"))
    lines: list[TextLine] = []

    if block_type == "text":
        for line_index, raw_line in enumerate(raw_block.get("lines") or []):
            lines.append(_extract_line(raw_line, block_id, line_index))

    text = "\n".join(line.text for line in lines if line.text)
    return TextBlock(
        block_id=block_id,
        type=block_type,
        bbox=bbox,
        text=text,
        lines=lines,
    )


def _extract_line(raw_line: dict, block_id: str, line_index: int) -> TextLine:
    line_id = f"{block_id}_l{line_index}"
    spans = [_extract_span(raw_span) for raw_span in raw_line.get("spans") or []]
    text = "".join(span.text for span in spans)
    return TextLine(
        line_id=line_id,
        bbox=_bbox(raw_line.get("bbox")),
        text=text,
        spans=spans,
    )


def _extract_span(raw_span: dict) -> TextSpan:
    font = raw_span.get("font")
    return TextSpan(
        text=str(raw_span.get("text") or ""),
        bbox=_bbox(raw_span.get("bbox")),
        font=str(font) if font else None,
        size=_optional_float(raw_span.get("size")),
        flags=_optional_int(raw_span.get("flags")),
    )


def _bbox(value: object) -> list[float]:
    if not value:
        return [0.0, 0.0, 0.0, 0.0]
    coords = [float(part) for part in list(value)[:4]]
    while len(coords) < 4:
        coords.append(0.0)
    return coords


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
