"""Build intermediate representation (IR) nodes from extracted text and metadata.

This module is the single entry point for constructing ``IRNode`` instances
with the required ``elements[]`` schema.  Downstream stages (LLM mapper,
XML generator) consume IR JSON — they never parse raw PDF text directly.

Example::

    from app.services.ir_builder import build_paragraph, build_display_math

    para = build_paragraph(
        "The energy is given by E=mc^2",
        source_block_ids=["p1_b10"],
        page_numbers=[1],
    )
    # para.elements == [
    #     IRTextElement(value="The energy is given by "),
    #     IRInlineMathElement(latex="E=mc^2"),  # if math detected
    # ]

    eq = build_display_math(
        "TAN = fTAN(XTAN)",
        source_block_ids=["p6_b43"],
        page_numbers=[6],
    )
    # eq.type == "display_math", eq.latex == "TAN = fTAN(XTAN)"
"""

from __future__ import annotations

import re
from typing import Sequence

from app.constants.ir_types import (
    IR_ABSTRACT,
    IR_DISPLAY_MATH,
    IR_HEADING,
    IR_INLINE_MATH,
    IR_INLINE_TEXT,
    IR_PARAGRAPH,
    IR_TABLE,
    SEMANTIC_TO_IR_TYPE,
)
from app.models.ir_schema import IRInlineMathElement, IRNode, IRTextElement
from app.utils.math_latex import (
    greek_to_latex,
    is_greek_character,
    is_plausible_display_equation,
    normalize_display_latex,
)
from app.utils.text_utils import normalize_text

# Inline math detection — conservative by design (false negative > false positive).
#
# Only two patterns are accepted:
#   1. $...$  — explicit LaTeX delimiters used by authors/vendors.
#   2. R^2 / R2 / R² — coefficient of determination; lookarounds prevent
#      substring matches inside tokens like AIR^2PLANE, PAIR^2ING, or R20.
#
# NOT treated as math (plain text):
#   - t-SNE, mse — algorithm names / abbreviations (IEEE uses <italic>, not
#     <inline-formula> for these).
#   - Chemistry formulas (NiCo2O4, Gd2O3, CO2) — chemical notation, not LaTeX.
_R_SQUARED_TOKEN = r"(?<![A-Za-z])R(?:\^2|2|\u00B2)(?![0-9])"
_INLINE_MATH_PATTERN = re.compile(
    r"(\$[^$]+\$|"  # explicit $...$ LaTeX delimiters
    rf"{_R_SQUARED_TOKEN}|"  # coefficient of determination
    r"[\u03B1-\u03C9\u0391-\u03A9])",  # Greek letters → inline LaTeX
    re.IGNORECASE,
)

# Whole-block display math: short lines with math symbols or known fragments.
_DISPLAY_MATH_WHOLE_BLOCK = re.compile(
    r"(=|∈|∑|∫|±|≤|≥|×|÷|√|\^|\{|\})",
)


def semantic_type_to_ir(semantic_type: str) -> str:
    """Map a legacy uppercase semantic label to a lowercase IR node type.

    Example::

        >>> semantic_type_to_ir("PARAGRAPH")
        'paragraph'
        >>> semantic_type_to_ir("EQUATION")
        'display_math'
    """
    return SEMANTIC_TO_IR_TYPE.get(semantic_type, "unknown")


def parse_inline_elements(text: str) -> list[IRTextElement | IRInlineMathElement]:
    """Split paragraph text into ``text`` and ``inline_math`` inline elements.

    Detects ``$...$`` delimited LaTeX and standalone ``R^2`` (word-bounded only).

    Example::

        >>> elems = parse_inline_elements("See $E=mc^2$ for details.")
        >>> elems[0].type
        'text'
        >>> elems[1].latex
        'E=mc^2'
    """
    if not text:
        return []

    elements: list[IRTextElement | IRInlineMathElement] = []
    position = 0

    for match in _INLINE_MATH_PATTERN.finditer(text):
        if match.start() > position:
            elements.append(IRTextElement(value=text[position : match.start()]))
        token = match.group(0)
        if token.startswith("$") and token.endswith("$"):
            elements.append(IRInlineMathElement(latex=greek_to_latex(token[1:-1])))
        elif re.fullmatch(r"R(?:\^2|2|\u00B2)", token, flags=re.IGNORECASE):
            elements.append(IRInlineMathElement(latex="R^2"))
        elif is_greek_character(token):
            elements.append(IRInlineMathElement(latex=greek_to_latex(token)))
        else:
            elements.append(IRInlineMathElement(latex=greek_to_latex(token)))
        position = match.end()

    if position < len(text):
        elements.append(IRTextElement(value=text[position:]))

    if not elements:
        elements.append(IRTextElement(value=text))

    return elements


def _should_use_display_math(text: str, ir_type: str) -> bool:
    """Return True when content should be modeled as display math."""
    if ir_type == IR_DISPLAY_MATH:
        return True
    normalized = normalize_text(text)
    if not normalized:
        return False
    # Lazy import avoids circular dependency with layout.semantic_builder.
    from app.services.layout.semantic_patterns import is_math_fragment

    if is_math_fragment(normalized):
        return True
    # Standalone R^2 in non-fragment text → inline math only, never display.
    if re.search(_R_SQUARED_TOKEN, normalized, flags=re.IGNORECASE):
        return False
    if len(normalized) < 80 and _DISPLAY_MATH_WHOLE_BLOCK.search(normalized):
        return True
    return False


def build_ir_node(
    semantic_type: str,
    text: str,
    *,
    source_block_ids: Sequence[str] | None = None,
    page_numbers: Sequence[int] | None = None,
    bbox: list[float] | None = None,
    confidence: float = 1.0,
    children: list[IRNode] | None = None,
    keywords: list[str] | None = None,
    heading: str | None = None,
    level: int | None = None,
    label: str | None = None,
    list_type: str | None = None,
    list_marker: str | None = None,
    rows: list[list[str]] | None = None,
    unknown_reason: str | None = None,
    detection_reason: str | None = None,
) -> IRNode:
    """Build an ``IRNode`` from a legacy semantic classification label and text.

    Example::

        >>> node = build_ir_node(
        ...     "PARAGRAPH",
        ...     "Energy is conserved.",
        ...     source_block_ids=["p2_b1"],
        ...     page_numbers=[2],
        ... )
        >>> node.type
        'paragraph'
        >>> node.elements[0].value
        'Energy is conserved.'
    """
    ir_type = semantic_type_to_ir(semantic_type)
    normalized = normalize_text(text)
    block_ids = list(source_block_ids or [])
    pages = sorted(set(page_numbers or []))

    if _should_use_display_math(normalized, ir_type) and (
        ir_type == IR_DISPLAY_MATH or is_plausible_display_equation(normalized)
    ):
        return IRNode(
            type=IR_DISPLAY_MATH,
            latex=normalize_display_latex(normalized),
            source_block_ids=block_ids,
            page_numbers=pages,
            bbox=bbox,
            confidence=confidence,
            label=label,
            heading=heading,
            level=level,
            unknown_reason=unknown_reason,
            detection_reason=detection_reason,
        )

    elements = parse_inline_elements(normalized) if normalized else []

    return IRNode(
        type=ir_type,
        elements=elements,
        children=children or [],
        source_block_ids=block_ids,
        page_numbers=pages,
        bbox=bbox,
        confidence=confidence,
        keywords=keywords or [],
        heading=heading,
        level=level,
        label=label,
        list_type=list_type,  # type: ignore[arg-type]
        list_marker=list_marker,
        rows=rows,
        unknown_reason=unknown_reason,
        detection_reason=detection_reason,
    )


def build_table(
    caption: str,
    rows: list[list[str]],
    *,
    source_block_ids: Sequence[str] | None = None,
    page_numbers: Sequence[int] | None = None,
    bbox: list[float] | None = None,
    confidence: float = 1.0,
    label: str | None = None,
) -> IRNode:
    """Build a table IR node with caption text and extracted grid rows."""
    normalized = normalize_text(caption)
    return IRNode(
        type=IR_TABLE,
        elements=[IRTextElement(value=normalized)] if normalized else [],
        rows=rows,
        label=label,
        source_block_ids=list(source_block_ids or []),
        page_numbers=sorted(set(page_numbers or [])),
        bbox=bbox,
        confidence=confidence,
    )


def build_paragraph(
    text: str,
    *,
    source_block_ids: Sequence[str] | None = None,
    page_numbers: Sequence[int] | None = None,
    bbox: list[float] | None = None,
    confidence: float = 1.0,
) -> IRNode:
    """Build a paragraph IR node with composable inline elements.

    Example::

        >>> p = build_paragraph("The value of $R^2$ is high.")
        >>> p.type
        'paragraph'
        >>> any(e.type == 'inline_math' for e in p.elements)
        True
    """
    return build_ir_node(
        "PARAGRAPH",
        text,
        source_block_ids=source_block_ids,
        page_numbers=page_numbers,
        bbox=bbox,
        confidence=confidence,
    )


def build_display_math(
    latex: str,
    *,
    source_block_ids: Sequence[str] | None = None,
    page_numbers: Sequence[int] | None = None,
    bbox: list[float] | None = None,
    confidence: float = 1.0,
    label: str | None = None,
) -> IRNode:
    """Build a display-math IR node.

    Example::

        >>> eq = build_display_math("TAN = fTAN(XTAN)")
        >>> eq.type
        'display_math'
        >>> eq.latex
        'TAN = fTAN(XTAN)'
    """
    return IRNode(
        type=IR_DISPLAY_MATH,
        latex=normalize_display_latex(latex),
        source_block_ids=list(source_block_ids or []),
        page_numbers=sorted(set(page_numbers or [])),
        bbox=bbox,
        confidence=confidence,
        label=label,
    )


def build_heading(
    text: str,
    *,
    level: int = 1,
    source_block_ids: Sequence[str] | None = None,
    page_numbers: Sequence[int] | None = None,
    bbox: list[float] | None = None,
    confidence: float = 1.0,
) -> IRNode:
    """Build a section heading IR node.

    Example::

        >>> h = build_heading("I. INTRODUCTION", level=1)
        >>> h.type
        'heading'
        >>> h.level
        1
    """
    normalized = normalize_text(text)
    return IRNode(
        type=IR_HEADING,
        elements=[IRTextElement(value=normalized)] if normalized else [],
        heading=normalized,
        level=level,
        source_block_ids=list(source_block_ids or []),
        page_numbers=sorted(set(page_numbers or [])),
        bbox=bbox,
        confidence=confidence,
    )


def build_abstract(
    text: str,
    *,
    source_block_ids: Sequence[str] | None = None,
    page_numbers: Sequence[int] | None = None,
    bbox: list[float] | None = None,
    confidence: float = 1.0,
) -> IRNode:
    """Build an abstract container with a child paragraph node.

    Example::

        >>> a = build_abstract("Abstract—In this approach...")
        >>> a.type
        'abstract'
        >>> a.children[0].type
        'paragraph'
    """
    paragraph = build_paragraph(
        text,
        source_block_ids=source_block_ids,
        page_numbers=page_numbers,
        bbox=bbox,
        confidence=confidence,
    )
    return IRNode(
        type=IR_ABSTRACT,
        elements=paragraph.elements,
        children=[paragraph],
        source_block_ids=list(source_block_ids or []),
        page_numbers=sorted(set(page_numbers or [])),
        bbox=bbox,
        confidence=confidence,
    )
