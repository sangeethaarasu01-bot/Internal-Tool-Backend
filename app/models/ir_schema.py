"""Intermediate representation (IR) schema for PDF → JATS pipeline.

Every extracted content block is represented as an ``IRNode`` with optional
composable ``elements[]`` for inline content (text, inline math).

Example — paragraph with inline math::

    {
        "type": "paragraph",
        "elements": [
            {"type": "text", "value": "The energy is given by "},
            {"type": "inline_math", "latex": "E=mc^2"}
        ],
        "source_block_ids": ["p1_b10"],
        "page_numbers": [1]
    }

Example — display equation::

    {
        "type": "display_math",
        "latex": "TAN = fTAN(XTAN)",
        "source_block_ids": ["p6_b43"],
        "page_numbers": [6]
    }
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field

from app.constants.ir_types import IR_TYPE_TO_JATS_TAG, IR_INLINE_MATH, IR_INLINE_TEXT

BBox = list[float]

ListStyle = Literal["bullet", "order"]


class IRTextElement(BaseModel):
    """Plain text inline content."""

    type: Literal["text"] = IR_INLINE_TEXT
    value: str


class IRInlineMathElement(BaseModel):
    """Inline mathematical expression in LaTeX notation."""

    type: Literal["inline_math"] = IR_INLINE_MATH
    latex: str


IRInlineElement = Annotated[
    IRTextElement | IRInlineMathElement,
    Field(discriminator="type"),
]


class IRNode(BaseModel):
    """Block-level intermediate representation node.

    Block types ``paragraph`` and ``heading`` carry composable ``elements[]``.
    Block type ``display_math`` carries a top-level ``latex`` field.
    Structural nodes (``list``, ``figure``, ``abstract``) may nest ``children``.
    """

    type: str
    elements: list[IRTextElement | IRInlineMathElement] = Field(default_factory=list)
    latex: str | None = None
    children: list[IRNode] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    bbox: BBox | None = None
    confidence: float = 1.0
    keywords: list[str] = Field(default_factory=list)
    label: str | None = None
    heading: str | None = None
    level: int | None = None
    list_type: ListStyle | None = None
    list_marker: str | None = None
    rows: list[list[str]] | None = None
    unknown_reason: str | None = None
    detection_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tag(self) -> str:
        """JATS tag name derived from the IR node type."""
        return IR_TYPE_TO_JATS_TAG.get(self.type, "unknown")

    @property
    def text(self) -> str:
        """Flat text view of inline content, children, or display-math latex.

        Useful for tests and backward-compatible string comparisons.
        """
        if self.elements:
            parts: list[str] = []
            for element in self.elements:
                if element.type == IR_INLINE_TEXT:
                    parts.append(element.value)
                else:
                    parts.append(element.latex)
            return "".join(parts)
        if self.latex is not None:
            return self.latex
        if self.children:
            return " ".join(child.text for child in self.children if child.text)
        return ""

    def has_inline_math(self) -> bool:
        """Return True when this node contains at least one inline math element."""
        return any(element.type == IR_INLINE_MATH for element in self.elements)

    def to_json_dict(self) -> dict:
        """Serialize to a JSON-compatible dict (for LLM / API output)."""
        return self.model_dump(mode="json", exclude_none=True)


# Backward-compatible alias used by older modules during migration.
SemanticElement = IRNode
