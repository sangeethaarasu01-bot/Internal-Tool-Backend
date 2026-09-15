"""Request/response models for Phase 2A extraction workflow endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScopeRequest(BaseModel):
    scope: str = Field(..., description="Canonical scope: front, body, back, or full")


class ScopeResponse(BaseModel):
    document_id: str
    scope: str
    allowed_sections: list[str]
    filtered_ir: dict[str, Any]
    filtered_template_schema: dict[str, Any] | None = None
    dropped_element_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class TemplateUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str
    template_id: str
    original_filename: str
    created_at: datetime
    template_schema: dict[str, Any] = Field(..., serialization_alias="schema")


class GenerateXmlRequest(BaseModel):
    scope: str = "full"
    use_llm: bool = False
    llm_fallback: bool = True


class GenerateXmlResponse(BaseModel):
    document_id: str
    scope: str
    mapping_source: str
    prompt_version: str | None = None
    xml_content: str
    warnings: list[str] = Field(default_factory=list)
    unmapped_content_count: int = 0
