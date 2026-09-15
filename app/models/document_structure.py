"""Intermediate representation for classified, ordered document structure."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.semantic_document import SemanticDocument

BBox = list[float]

BlockClassification = Literal[
    "TITLE",
    "AUTHOR",
    "AFFILIATION",
    "ABSTRACT",
    "KEYWORDS",
    "SECTION",
    "SUBSECTION",
    "PARAGRAPH",
    "REFERENCE_TEXT",
    "FIGURE",
    "TABLE",
    "CAPTION",
    "EQUATION",
    "RUNNING_HEADER",
    "PAGE_NUMBER",
    "FOOTER",
    "BODY_TEXT",
    "UNKNOWN_TEXT",
]

ColumnPosition = Literal["LEFT", "RIGHT", "FULL_WIDTH"]


class ExcludedBlock(BaseModel):
    block_id: str
    page_number: int
    classification: BlockClassification
    reason: str
    text: str
    char_count: int
    bbox: BBox


class CompletenessReport(BaseModel):
    raw_char_count: int = 0
    retained_char_count: int = 0
    excluded_char_count: int = 0
    unclassified_char_count: int = 0
    excluded_blocks: list[ExcludedBlock] = Field(default_factory=list)
    exclusion_summary: dict[str, int] = Field(default_factory=dict)


class ProcessedBlock(BaseModel):
    block_id: str
    page_number: int
    reading_order_index: int
    column: ColumnPosition
    classification: BlockClassification
    confidence: float = 1.0
    exclude_from_content: bool = False
    exclusion_reason: str | None = None
    bbox: BBox
    text: str
    block_type: str
    dominant_font: str | None = None
    dominant_font_size: float | None = None
    is_bold: bool = False


class StructuredItem(BaseModel):
    type: str
    text: str
    page_number: int
    source_block_ids: list[str] = Field(default_factory=list)
    content_source_block_ids: list[str] = Field(default_factory=list)
    bbox: BBox | None = None
    heading: str | None = None


class SectionNode(BaseModel):
    heading: str
    heading_block_ids: list[str] = Field(default_factory=list)
    level: int = 1
    page_number: int
    items: list[StructuredItem] = Field(default_factory=list)
    content_source_block_ids: list[str] = Field(default_factory=list)


class StructureStats(BaseModel):
    detected_sections: int = 0
    detected_paragraphs: int = 0
    detected_references: int = 0
    unknown_blocks: int = 0
    running_headers: int = 0
    page_numbers: int = 0
    footers: int = 0


class DocumentStructureResult(BaseModel):
    pipeline_version: str = "2.0.0"
    blocks: list[ProcessedBlock] = Field(default_factory=list)
    sections: list[SectionNode] = Field(default_factory=list)
    paragraphs: list[StructuredItem] = Field(default_factory=list)
    references: list[StructuredItem] = Field(default_factory=list)
    unknown_items: list[StructuredItem] = Field(default_factory=list)
    completeness: CompletenessReport = Field(default_factory=CompletenessReport)
    structure_stats: StructureStats = Field(default_factory=StructureStats)
    semantic: SemanticDocument | None = None
