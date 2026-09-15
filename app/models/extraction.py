from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.document_structure import DocumentStructureResult


BBox = list[float]


class TextSpan(BaseModel):
    text: str
    bbox: BBox
    font: str | None = None
    size: float | None = None
    flags: int | None = None


class TextLine(BaseModel):
    line_id: str
    bbox: BBox
    text: str
    spans: list[TextSpan] = Field(default_factory=list)


class TextBlock(BaseModel):
    block_id: str
    type: str
    bbox: BBox
    text: str
    lines: list[TextLine] = Field(default_factory=list)


class ExtractedTable(BaseModel):
    """Grid extracted via PyMuPDF ``find_tables()``."""

    table_id: str
    page_number: int
    rows: list[list[str]] = Field(default_factory=list)
    bbox: BBox | None = None


class PageExtraction(BaseModel):
    page_number: int
    width: float
    height: float
    text_char_count: int
    requires_ocr: bool
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    title: str | None = None
    author: str | None = None
    creator: str | None = None
    producer: str | None = None
    creation_date: str | None = None
    modification_date: str | None = None


class DocumentInfo(BaseModel):
    filename: str
    page_count: int
    requires_ocr: bool
    ocr_applied: bool = False
    extraction_engine: str = "pymupdf"
    extraction_version: str = "1.0.0"
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


class ExtractionStats(BaseModel):
    total_blocks: int = 0
    total_lines: int = 0
    total_chars: int = 0
    pages_with_low_text: list[int] = Field(default_factory=list)
    pages_with_no_text: list[int] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    document: DocumentInfo
    pages: list[PageExtraction] = Field(default_factory=list)
    stats: ExtractionStats = Field(default_factory=ExtractionStats)
    structure: DocumentStructureResult | None = None


class ExtractionStartResponse(BaseModel):
    extraction_id: str
    status: Literal["queued", "processing"]
    filename: str
    message: str = "Extraction started"


class ExtractionRecord(BaseModel):
    extraction_id: str
    filename: str
    original_filename: str
    status: str
    page_count: int | None = None
    requires_ocr: bool | None = None
    ocr_applied: bool = False
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    result: ExtractionResult | None = None
