"""Shared types for generic table extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EngineName = Literal[
    "camelot-lattice",
    "camelot-stream",
    "img2table",
    "pymupdf",
    "pdfplumber",
    "borderless-grid",
    "ocr-grid",
]


@dataclass
class TextBlockInfo:
    text: str
    bbox: list[float]
    is_bold: bool = False


@dataclass
class CaptionInfo:
    text: str
    bbox: list[float]
    caption_type: Literal["table", "figure"]


@dataclass
class PageIngest:
    page_number: int
    page_width: float
    page_height: float
    raw_text: str
    blocks: list[TextBlockInfo]
    captions: list[CaptionInfo]
    figure_regions: list[list[float]]
    png_path: str | None = None
    image_width: int = 0
    image_height: int = 0


@dataclass
class RawDetectedTable:
    rows: list[list[str]]
    bbox: list[float]
    engine: EngineName
    page_number: int
    bound_caption: str | None = None


@dataclass
class ProcessedTable:
    table_id: str
    page_number: int
    caption: str | None
    caption_confidence: float
    headers: list[str]
    rows: list[list[str]]
    bbox: list[float]
    engine: EngineName
    warnings: list[str] = field(default_factory=list)
    caption_detected: bool = False
    status: Literal["structured", "partial", "rejected"] = "structured"
    reject_reason: str | None = None
    confidence: float = 0.0
