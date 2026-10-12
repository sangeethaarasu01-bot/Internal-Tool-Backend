"""Phase 1 intermediate representation — PDF extraction without LLM involvement."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PdfDocumentKind = Literal["text_based", "scanned_image_based", "mixed", "unknown"]
PublicationDocumentType = Literal["research_paper", "book", "review", "unknown"]
ExtractedDocumentKind = Literal["text_based", "scanned_image_based", "mixed", "unknown", "book"]

HeadingKind = Literal[
    "heading_candidate",
    "section",
    "subsection",
    "paragraph",
    "equation",
    "caption",
    "other",
]

ColumnLayoutKind = Literal["single", "two_column", "mixed", "unknown"]
TableExtractionStatus = Literal["structured", "partial", "failed"]
FigureKind = Literal["figure", "logo", "author_photo", "decorative", "uncertain"]


class ExtractedParagraph(BaseModel):
    """A text unit on a page, preserving reading order where possible."""

    text: str
    kind: HeadingKind = "paragraph"
    source_block_ids: list[str] = Field(default_factory=list)
    dominant_font_size: float | None = None
    is_bold: bool = False
    reading_order_index: int | None = None
    column: str | None = None
    bbox: list[float] | None = None


class ExtractedPage(BaseModel):
    page_number: int
    width: float
    height: float
    char_count: int
    is_empty: bool
    requires_ocr: bool
    column_layout: ColumnLayoutKind = "unknown"
    paragraphs: list[ExtractedParagraph] = Field(default_factory=list)
    paragraph_group_block_ids: list[list[str]] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    equation_ids: list[str] = Field(default_factory=list)
    raw_page_text: str = ""


class ExtractedSection(BaseModel):
    """Heuristic section grouping (not yet semantically typed for templates)."""

    heading: str
    level: int = 1
    page_number: int
    parent_heading: str | None = None
    content: str = ""
    source_block_ids: list[str] = Field(default_factory=list)


class TableExtractionQuality(BaseModel):
    confidence: float = 0.0
    status: TableExtractionStatus = "failed"
    engine: str = "pymupdf"
    caption_detected: bool = False
    structured_grid: bool = False
    warnings: list[str] = Field(default_factory=list)


class ExtractedTableSummary(BaseModel):
    """Backward-compatible table summary; extended fields optional in Phase 1.1+."""

    table_id: str
    page_number: int
    row_count: int = 0  # Total rows in ``rows`` (header included when present).
    column_count: int = 0
    rows: list[list[str]] = Field(default_factory=list)
    bbox: list[float] | None = None
    id: str | None = None
    caption: str | None = None
    subtitle: str | None = None
    headers: list[str] = Field(default_factory=list)
    raw_text: str | None = None
    merged_cells: list[dict[str, int]] = Field(default_factory=list)
    extraction_quality: TableExtractionQuality | None = None


class FigureExtractionQuality(BaseModel):
    image_extracted: bool = False
    caption_detected: bool = False
    confidence: float = 0.0
    classification: FigureKind = "uncertain"
    warnings: list[str] = Field(default_factory=list)


class ExtractedSubfigure(BaseModel):
    label: str
    bbox: list[float]


class ExtractedFigure(BaseModel):
    figure_id: str
    page_number: int
    figure_number: int | None = None
    subfigures: list[ExtractedSubfigure] | None = None
    bbox: list[float] | None = None
    id: str | None = None
    image_path: str | None = None
    caption: str | None = None
    caption_bbox: list[float] | None = None
    figure_kind: FigureKind = "uncertain"
    xref: int | None = None
    extraction_engine: str | None = None
    extraction_quality: FigureExtractionQuality = Field(default_factory=FigureExtractionQuality)


class EquationExtractionQuality(BaseModel):
    confidence: float = 0.0
    label_detected: bool = False
    contains_control_chars: bool = False


class ExtractedEquation(BaseModel):
    equation_id: str
    page_number: int
    raw_text: str
    bbox: list[float] | None = None
    label: str | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    extraction_quality: EquationExtractionQuality = Field(default_factory=EquationExtractionQuality)


class ExtractedCaption(BaseModel):
    caption_id: str
    page_number: int
    caption_type: Literal["figure", "table", "unknown"]
    text: str
    bbox: list[float] | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    linked_object_id: str | None = None


class ExtractedReferenceItem(BaseModel):
    text: str
    page_number: int
    source_block_ids: list[str] = Field(default_factory=list)


class InvalidCharacterPageSummary(BaseModel):
    page_number: int
    invalid_character_count: int = 0
    code_points: list[int] = Field(default_factory=list)
    occurrences_by_code: dict[str, int] = Field(default_factory=dict)


class InvalidCharacterReport(BaseModel):
    """XML-illegal control characters present in raw PyMuPDF text (forensic)."""

    invalid_character_occurrences: int = 0
    distinct_code_points: list[int] = Field(default_factory=list)
    occurrences_by_code: dict[str, int] = Field(default_factory=dict)
    characters_removed_for_xml: int = 0
    affected_pages: list[InvalidCharacterPageSummary] = Field(default_factory=list)
    raw_character_count: int = 0
    normalized_character_count: int = 0
    origin_hint: str = ""
    xml_sanitization_warning_source: str = ""
    warnings: list[str] = Field(default_factory=list)


class TextQualitySummary(BaseModel):
    retention_ratio: float | None = None
    unclassified_ratio: float | None = None
    multi_column_page_numbers: list[int] = Field(default_factory=list)
    reading_order_engine: str = "layout_column_interleave"


class ExtractionQualityIndicators(BaseModel):
    pdf_document_kind: PdfDocumentKind = "unknown"
    page_count: int = 0
    extracted_character_count: int = 0
    invalid_character_report: InvalidCharacterReport | None = None
    text_quality: TextQualitySummary | None = None
    empty_page_numbers: list[int] = Field(default_factory=list)
    low_text_page_numbers: list[int] = Field(default_factory=list)
    requires_ocr: bool = False
    ocr_applied: bool = False
    text_retention_ratio: float | None = None
    unclassified_char_ratio: float | None = None
    detected_section_count: int = 0
    detected_table_count: int = 0
    tables_extracted: int = 0
    tables_structured: int = 0
    detected_reference_count: int = 0
    figure_count: int = 0
    figures_extracted: int = 0
    caption_count: int = 0
    equation_count: int = 0
    inline_equation_count: int = 0
    control_character_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    """
    Normalized Phase 1 document view.

    Fields are best-effort; ``raw_text`` always retains the full ordered extract
    so downstream stages can recover content that heuristics miss.
    """

    schema_version: str = "1.1.0"
    source_filename: str
    document_type: ExtractedDocumentKind = "unknown"
    publication_document_type: PublicationDocumentType = "research_paper"
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    publication_year: int | None = None
    isbn: str | None = None
    isbns: list[str] = Field(default_factory=list)
    copyright_holder: str | None = None
    pages: list[ExtractedPage] = Field(default_factory=list)
    sections: list[ExtractedSection] = Field(default_factory=list)
    tables: list[ExtractedTableSummary] = Field(default_factory=list)
    figures: list[ExtractedFigure] = Field(default_factory=list)
    equations: list[ExtractedEquation] = Field(default_factory=list)
    captions: list[ExtractedCaption] = Field(default_factory=list)
    references: list[ExtractedReferenceItem] = Field(default_factory=list)
    raw_text: str = ""
    normalized_text: str = ""
    extraction_quality: ExtractionQualityIndicators = Field(
        default_factory=ExtractionQualityIndicators
    )
    # Full low-level extract (blocks, lines, spans) for debugging — optional in API responses.
    detailed_extraction_included: bool = False
