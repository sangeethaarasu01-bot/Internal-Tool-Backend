"""Pydantic models for LLM semantic mapping output (Phase 2B)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


ALLOWED_SEMANTIC_TYPES = frozenset(
    {
        "paragraph",
        "heading",
        "subsection",
        "inline_math",
        "display_math",
        "figure",
        "table",
        "reference",
        "author",
        "affiliation",
        "abstract",
        "keywords",
        "caption",
        "metadata",
        "list",
        "list_item",
        "unknown",
    }
)


class MappedInlineElement(BaseModel):
    type: str
    value: str | None = None
    latex: str | None = None


class MappedSemanticNode(BaseModel):
    """A single semantically mapped content node."""

    semantic_type: str
    template_path: str | None = None
    source_node_ids: list[str] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    text: str | None = None
    latex: str | None = None
    label: str | None = None
    elements: list[MappedInlineElement] = Field(default_factory=list)
    rows: list[list[str]] | None = None
    children: list[MappedSemanticNode] = Field(default_factory=list)
    confidence: float | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("semantic_type")
    @classmethod
    def validate_semantic_type(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_")
        if normalized not in ALLOWED_SEMANTIC_TYPES:
            raise ValueError(f"Unsupported semantic_type: {value}")
        return normalized


class UnmappedContent(BaseModel):
    source_node_ids: list[str] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    reason: str
    ir_type: str | None = None
    ir_snapshot: dict[str, Any] | None = None


class SemanticMappingBody(BaseModel):
    """Template-driven mapping partitioned by article section."""

    front: dict[str, Any] = Field(default_factory=dict)
    body: list[MappedSemanticNode] = Field(default_factory=list)
    back: dict[str, Any] = Field(default_factory=dict)


class LlmMappingPayload(BaseModel):
    """Raw mapping payload returned by the LLM (before document metadata)."""

    mapping: SemanticMappingBody
    unmapped_content: list[UnmappedContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SemanticMappingResult(BaseModel):
    """Complete semantic mapping response."""

    document_id: str
    scope: str
    prompt_version: str
    mapping: SemanticMappingBody
    unmapped_content: list[UnmappedContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SemanticMapRequest(BaseModel):
    scope: str = "full"


class SemanticMapResponse(BaseModel):
    document_id: str
    scope: str
    prompt_version: str
    mapping: SemanticMappingBody
    unmapped_content: list[UnmappedContent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
