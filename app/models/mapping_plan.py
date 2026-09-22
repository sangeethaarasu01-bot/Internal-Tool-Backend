"""Semantic mapping from PDF fields to XML XPaths."""

from typing import Literal

from pydantic import BaseModel, Field


class MappingEntry(BaseModel):
    xml_xpath: str
    xml_tag: str
    pdf_field: str
    transform: Literal[
        "none",
        "loop",
        "loop_with_label_split",
        "escape_xml",
        "to_latex",
        "to_iso_date",
        "custom",
    ] = "none"
    transform_arg: str | None = None
    confidence: float = 0.0
    reasoning: str = ""


class MappingPlan(BaseModel):
    mappings: list[MappingEntry] = Field(default_factory=list)
    unmapped_xml: list[str] = Field(default_factory=list)
    unmapped_pdf: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    llm_model: str = ""
    llm_cost_usd: float = 0.0
