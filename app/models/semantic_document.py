"""Semantic document structure built on the elements[] IR schema.

The document is partitioned into ``front``, ``body``, and ``back`` sections.
Each content node is an :class:`~app.models.ir_schema.IRNode` with composable
``elements[]`` for inline text and math.

Example document shape::

    {
        "front": {
            "title": {
                "type": "title",
                "elements": [{"type": "text", "value": "Paper Title"}]
            }
        },
        "body": {
            "sections": [{
                "heading": "I. INTRODUCTION",
                "heading_element": {"type": "heading", "elements": [...]},
                "content": [{"type": "paragraph", "elements": [...]}]
            }]
        }
    }
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.ir_schema import IRNode

# Re-export for callers that imported SemanticElement from this module.
SemanticElement = IRNode

BBox = list[float]


class SemanticSection(BaseModel):
    """A body section with heading and nested content nodes."""

    heading: str
    heading_element: IRNode
    level: int = 1
    paragraphs: list[IRNode] = Field(default_factory=list)
    subsections: list[SemanticSection] = Field(default_factory=list)
    content: list[IRNode] = Field(default_factory=list)
    content_source_block_ids: list[str] = Field(default_factory=list)


class SemanticFrontMatter(BaseModel):
    """Front-matter nodes (title, authors, abstract, keywords, etc.)."""

    journal_header: IRNode | None = None
    page_number: IRNode | None = None
    title: IRNode | None = None
    authors: list[IRNode] = Field(default_factory=list)
    affiliations: list[IRNode] = Field(default_factory=list)
    date_history: IRNode | None = None
    corresponding_author: IRNode | None = None
    abstract: IRNode | None = None
    keywords: IRNode | None = None
    other: list[IRNode] = Field(default_factory=list)


class SemanticBody(BaseModel):
    """Body sections and unattached paragraphs."""

    sections: list[SemanticSection] = Field(default_factory=list)
    loose_paragraphs: list[IRNode] = Field(default_factory=list)


class SemanticBackMatter(BaseModel):
    """Back-matter nodes (references, bios, acknowledgments)."""

    reference_list: IRNode | None = None
    references: list[IRNode] = Field(default_factory=list)
    other: list[IRNode] = Field(default_factory=list)


class SemanticCompletenessReport(BaseModel):
    """Coverage statistics for the extraction → IR mapping."""

    raw_character_count: int = 0
    structured_character_count: int = 0
    excluded_character_count: int = 0
    unknown_element_count: int = 0
    unmapped_block_ids: list[str] = Field(default_factory=list)


class SemanticDocument(BaseModel):
    """Root IR document produced by Stage 1 of the pipeline."""

    pipeline_version: str = "2.0.0"
    front: SemanticFrontMatter = Field(default_factory=SemanticFrontMatter)
    body: SemanticBody = Field(default_factory=SemanticBody)
    back: SemanticBackMatter = Field(default_factory=SemanticBackMatter)
    unknown: list[IRNode] = Field(default_factory=list)
    completeness: SemanticCompletenessReport = Field(default_factory=SemanticCompletenessReport)
    tagged_output: str = ""

    def to_ir_json(self) -> dict:
        """Serialize the full document IR to a JSON-compatible dict.

        Example::

            doc = build_semantic_document(raw, processed)
            payload = doc.to_ir_json()
            assert "front" in payload and "body" in payload
        """
        return self.model_dump(mode="json", exclude={"tagged_output"}, exclude_none=True)
