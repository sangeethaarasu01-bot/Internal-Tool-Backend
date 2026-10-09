"""Models for parsed DocBook 5.0 book templates."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocBookIdentifier(BaseModel):
    kind: str
    role: str | None = None
    value: str


class DocBookBookMetadata(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    isbns: list[DocBookIdentifier] = Field(default_factory=list)
    doi: str | None = None
    copyright_year: str | None = None
    copyright_holder: str | None = None


class DocBookStructureNode(BaseModel):
    """Lightweight tree node preserving DocBook hierarchy (local names + attrs)."""

    tag: str
    namespace_uri: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    text_preview: str | None = None
    children: list[DocBookStructureNode] = Field(default_factory=list)


class DocBookTemplateParseResult(BaseModel):
    template_format: str = "docbook_5_book"
    root_namespace: str
    version: str | None = None
    metadata: DocBookBookMetadata
    structure: DocBookStructureNode
