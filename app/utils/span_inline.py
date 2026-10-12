"""Build IR inline elements from PDF span flags (bold, italic, super/subscript)."""

from __future__ import annotations

import re
from contextvars import ContextVar
from statistics import median

from app.models.extraction import ExtractionResult, TextBlock, TextSpan
from app.models.ir_schema import IRInlineMathElement, IRTextElement
from app.services.ir_builder import parse_inline_elements

_EXTRACTION_RAW: ContextVar[ExtractionResult | None] = ContextVar(
    "extraction_raw_for_inline",
    default=None,
)


def set_extraction_raw_for_inline(raw: ExtractionResult | None) -> None:
    _EXTRACTION_RAW.set(raw)


_FONT_BOLD = 16
_FONT_ITALIC = 2
_FONT_SUPERSCRIPT = 1

_UNICODE_SUPERSCRIPT = str.maketrans(
    {
        "\u00b2": "2",
        "\u00b3": "3",
        "\u00b9": "1",
        "\u2070": "0",
        "\u2074": "4",
        "\u2075": "5",
        "\u2076": "6",
        "\u2077": "7",
        "\u2078": "8",
        "\u2079": "9",
    }
)


def _span_styles(span: TextSpan, line_median_size: float | None) -> tuple[bool, bool, bool, bool]:
    flags = span.flags or 0
    bold = bool(flags & _FONT_BOLD)
    italic = bool(flags & _FONT_ITALIC)
    superscript = bool(flags & _FONT_SUPERSCRIPT)
    subscript = False
    if not superscript and span.size and line_median_size and line_median_size > 0:
        if span.size <= line_median_size * 0.78:
            superscript = True
    return bold, italic, superscript, subscript


def _line_median_size(spans: list[TextSpan]) -> float | None:
    sizes = [span.size for span in spans if span.size]
    if not sizes:
        return None
    return float(median(sizes))


def _merge_adjacent_text_elements(
    elements: list[IRTextElement | IRInlineMathElement],
) -> list[IRTextElement | IRInlineMathElement]:
    if not elements:
        return []
    merged: list[IRTextElement | IRInlineMathElement] = []
    for element in elements:
        if isinstance(element, IRInlineMathElement):
            merged.append(element)
            continue
        if (
            merged
            and isinstance(merged[-1], IRTextElement)
            and merged[-1].bold == element.bold
            and merged[-1].italic == element.italic
            and merged[-1].superscript == element.superscript
            and merged[-1].subscript == element.subscript
        ):
            merged[-1] = IRTextElement(
                value=merged[-1].value + element.value,
                bold=element.bold,
                italic=element.italic,
                superscript=element.superscript,
                subscript=element.subscript,
            )
        else:
            merged.append(element)
    return merged


def _split_unicode_superscript_runs(
    text: str,
    *,
    bold: bool,
    italic: bool,
    superscript: bool = False,
    subscript: bool = False,
) -> list[IRTextElement]:
    if not text:
        return []
    parts: list[IRTextElement] = []
    position = 0
    for match in re.finditer(r"[\u00b2\u00b3\u00b9\u2070-\u2079]", text):
        if match.start() > position:
            parts.append(
                IRTextElement(
                    value=text[position : match.start()],
                    bold=bold,
                    italic=italic,
                    superscript=superscript,
                    subscript=subscript,
                )
            )
        digit = text[match.start()].translate(_UNICODE_SUPERSCRIPT)
        parts.append(IRTextElement(value=digit, superscript=True, bold=bold, italic=italic))
        position = match.end()
    if position < len(text):
        parts.append(
            IRTextElement(
                value=text[position:],
                bold=bold,
                italic=italic,
                superscript=superscript,
                subscript=subscript,
            )
        )
    return parts if parts else [
        IRTextElement(
            value=text,
            bold=bold,
            italic=italic,
            superscript=superscript,
            subscript=subscript,
        )
    ]


def _expand_text_element_with_math(element: IRTextElement) -> list[IRTextElement | IRInlineMathElement]:
    expanded: list[IRTextElement | IRInlineMathElement] = []
    for piece in _split_unicode_superscript_runs(
        element.value,
        bold=element.bold,
        italic=element.italic,
        superscript=element.superscript,
        subscript=element.subscript,
    ):
        for parsed in parse_inline_elements(piece.value):
            if isinstance(parsed, IRInlineMathElement):
                expanded.append(parsed)
            else:
                expanded.append(
                    IRTextElement(
                        value=parsed.value,
                        bold=piece.bold,
                        italic=piece.italic,
                        superscript=piece.superscript,
                        subscript=piece.subscript,
                    )
                )
    return expanded


def inline_elements_from_text_block(block: TextBlock) -> list[IRTextElement | IRInlineMathElement]:
    styled: list[IRTextElement | IRInlineMathElement] = []
    for line in block.lines:
        median_size = _line_median_size(line.spans)
        for span in line.spans:
            if not span.text:
                continue
            bold, italic, superscript, subscript = _span_styles(span, median_size)
            styled.append(
                IRTextElement(
                    value=span.text,
                    bold=bold,
                    italic=italic,
                    superscript=superscript,
                    subscript=subscript,
                )
            )
    if not styled:
        return parse_inline_elements(block.text or "")
    expanded: list[IRTextElement | IRInlineMathElement] = []
    for element in styled:
        if isinstance(element, IRInlineMathElement):
            expanded.append(element)
        else:
            expanded.extend(_expand_text_element_with_math(element))
    return _merge_adjacent_text_elements(expanded)


def inline_elements_from_source_blocks(
    raw: ExtractionResult | None,
    source_block_ids: list[str],
    *,
    fallback_text: str,
) -> list[IRTextElement | IRInlineMathElement] | None:
    if raw is None:
        raw = _EXTRACTION_RAW.get()
    if not raw or not source_block_ids:
        return None
    by_id: dict[str, TextBlock] = {}
    for page in raw.pages:
        for block in page.blocks:
            by_id[block.block_id] = block
    blocks = [by_id[block_id] for block_id in source_block_ids if block_id in by_id]
    if not blocks:
        return None
    if not any(line.spans for block in blocks for line in block.lines):
        return None
    combined: list[IRTextElement | IRInlineMathElement] = []
    for block in blocks:
        combined.extend(inline_elements_from_text_block(block))
    return _merge_adjacent_text_elements(combined) if combined else None
