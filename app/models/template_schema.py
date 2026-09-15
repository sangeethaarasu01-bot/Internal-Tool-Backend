"""Pydantic models for template_schema.json consumed by LLM mapper and XML generator."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RootAttributeSpec(BaseModel):
    """Specification for a root-element attribute."""

    required: bool = False
    values: list[str] = Field(default_factory=list)
    default: str | None = None


class TagSpec(BaseModel):
    """Schema for a single JATS tag."""

    allowed_children: list[str] = Field(default_factory=list)
    allowed_attributes: list[str] = Field(default_factory=list)
    cardinality: dict[str, str] = Field(default_factory=dict)
    text_content: bool = False


class SectionBoundarySpec(BaseModel):
    """Direct and descendant tags within a top-level article section."""

    direct_children: list[str] = Field(default_factory=list)
    descendants: list[str] = Field(default_factory=list)


class LlmHints(BaseModel):
    """Hints for the LLM semantic mapper (Phase 3)."""

    must_not_hallucinate: list[str] = Field(default_factory=list)
    prefer_extract_over_generate: bool = True


class TemplateSchema(BaseModel):
    """Machine-readable template schema derived from a reference XML template."""

    template_name: str
    template_source: str
    root_tag: str = "article"
    root_attributes: dict[str, RootAttributeSpec] = Field(default_factory=dict)
    tags: dict[str, TagSpec] = Field(default_factory=dict)
    section_boundaries: dict[str, SectionBoundarySpec] = Field(default_factory=dict)
    scope_markers: dict[str, list[str]] = Field(default_factory=dict)
    required_paths: list[str] = Field(default_factory=list)
    known_attributes: dict[str, list[str]] = Field(default_factory=dict)
    llm_hints: LlmHints = Field(default_factory=LlmHints)

    def get_scope_sections(self, scope: str) -> list[str]:
        """Return top-level section names for a scope instruction."""
        return self.scope_markers.get(scope, [])

    def tags_for_section(self, section: str, *, include_direct: bool = True) -> list[str]:
        """Return tag names associated with a section boundary."""
        boundary = self.section_boundaries.get(section)
        if boundary is None:
            return []
        if include_direct:
            return _merge_unique(boundary.direct_children, boundary.descendants)
        return list(boundary.descendants)


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in base + extra:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged
