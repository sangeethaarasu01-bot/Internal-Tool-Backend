"""Pydantic models for analyzed XML template schema."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SchemaElement(BaseModel):
    xpath: str
    tag: str
    semantic: str
    cardinality: Literal["single", "repeating"]
    data_type: Literal["string", "number", "date", "url", "xml_fragment", "latex", "empty"]
    required: bool
    attributes: dict[str, str] = Field(default_factory=dict)
    sample: str = ""
    children: list[SchemaElement] = Field(default_factory=list)
    notes: str = ""


class SchemaMap(BaseModel):
    root_tag: str
    namespaces: dict[str, str] = Field(default_factory=dict)
    doctype: str | None = None
    elements: list[SchemaElement]
    template_hash: str
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    llm_model: str = ""
    llm_cost_usd: float = 0.0
