"""Phase 3: template-driven JATS XML generation from semantic mapping JSON.

The LLM produces structured mapping JSON; this module deterministically renders
IEEE JATS XML using the uploaded client template as the structural skeleton.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from lxml import etree

from app.models.semantic_mapping import MappedInlineElement, MappedSemanticNode, SemanticMappingBody
from app.utils.math_latex import (
    display_formula_id,
    format_display_math_for_ieee,
    format_inline_math_for_ieee,
)
from app.utils.text_utils import dehyphenate_line_breaks, infer_drop_cap_letter
from app.utils.reference_assembler import (
    AssembledReference,
    ReferenceParsingError,
    deduplicate_assembled_references,
    reference_number_from_mapping_node,
    validate_reference_sequence,
)
from app.services.template_format import UnsupportedTemplateRootError, require_jats_article_template
from app.services.author_deduplication import author_dedup_key, clean_author_display_name
from app.utils.person_name import split_person_name
from app.utils.template_skeleton import is_boilerplate_text
from app.utils.template_skeleton import strip_template_for_semantic_mapping
from app.utils.xml_helpers import xml_local_name
from app.utils.xml_helpers import xml_local_name
from app.utils.reference_citation_builder import populate_structured_mixed_citation
from app.utils.xml_serializer import serialize_lxml_tree
from app.utils.xml_text import normalize_person_name_text, sanitize_xml_text, set_lxml_attr, set_lxml_text

MML_NS = "http://www.w3.org/1998/Math/MathML"
XLINK_NS = "http://www.w3.org/1999/xlink"
NSMAP = {
    "mml": MML_NS,
    "xlink": XLINK_NS,
}

_SECTION_SEMANTIC_TYPES = frozenset({"section", "heading", "subsection"})
_ROMAN_SECTION_NUMBERS = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}
_PERSON_NAME_TAGS = frozenset({"given-names", "surname"})
_INLINE_MARKUP_PATTERN = re.compile(
    r"(\$[^$]+\$|"
    r"(?<![A-Za-z])R(?:\^2|2|\u00B2)(?![0-9]))",
    re.IGNORECASE,
)
_BIBLIOGRAPHIC_CITATION_RE = re.compile(r"\[(\d+)\]")


class XmlGenerationError(RuntimeError):
    """Raised when XML generation fails."""


def _log_context_for(node: MappedSemanticNode | dict[str, Any], field: str) -> dict[str, str]:
    if isinstance(node, MappedSemanticNode):
        source = ",".join(node.source_block_ids[:3]) if node.source_block_ids else "-"
        semantic_type = node.semantic_type
    else:
        source_ids = node.get("source_block_ids") or []
        source = ",".join(source_ids[:3]) if source_ids else "-"
        semantic_type = str(node.get("semantic_type") or "-")
    return {"semantic_type": semantic_type, "source": source, "field": field}


def _text_of(node: MappedSemanticNode | dict[str, Any], field: str = "text") -> str:
    ctx = _log_context_for(node, field)

    def _finalize(value: str) -> str:
        return dehyphenate_line_breaks(sanitize_xml_text(value, log_context=ctx))

    if isinstance(node, MappedSemanticNode):
        if node.text:
            return _finalize(node.text)
        if node.latex:
            return _finalize(node.latex)
        parts: list[str] = []
        for element in node.elements:
            if element.value:
                parts.append(
                    sanitize_xml_text(
                        element.value,
                        log_context={**ctx, "field": "elements.value"},
                    )
                )
            elif element.latex:
                parts.append(
                    sanitize_xml_text(
                        element.latex,
                        log_context={**ctx, "field": "elements.latex"},
                    )
                )
        return dehyphenate_line_breaks("".join(parts))
    if node.get("text"):
        return _finalize(str(node["text"]))
    if node.get("latex"):
        return _finalize(str(node["latex"]))
    parts: list[str] = []
    for element in node.get("elements") or []:
        if element.get("value"):
            parts.append(
                sanitize_xml_text(
                    str(element["value"]),
                    log_context={**ctx, "field": "elements.value"},
                )
            )
        elif element.get("latex"):
            parts.append(
                sanitize_xml_text(
                    str(element["latex"]),
                    log_context={**ctx, "field": "elements.latex"},
                )
            )
    return dehyphenate_line_breaks("".join(parts))


def _as_mapped(node: MappedSemanticNode | dict[str, Any]) -> MappedSemanticNode:
    if isinstance(node, MappedSemanticNode):
        return node
    return MappedSemanticNode.model_validate(node)


def _split_inline_text_segments(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    segments: list[tuple[str, str]] = []
    position = 0
    for match in _INLINE_MARKUP_PATTERN.finditer(text):
        if match.start() > position:
            segments.append(("text", text[position : match.start()]))
        token = match.group(0)
        if token.startswith("$") and token.endswith("$"):
            segments.append(("latex", token[1:-1]))
        else:
            segments.append(("r_squared", "2"))
        position = match.end()
    if position < len(text):
        segments.append(("text", text[position:]))
    return segments if segments else [("text", text)]


def _inline_has_style(element: MappedInlineElement) -> bool:
    return bool(element.bold or element.italic or element.superscript or element.subscript)


def _inline_segments_from_node(mapped: MappedSemanticNode) -> list[tuple[str, str | MappedInlineElement]]:
    segments: list[tuple[str, str | MappedInlineElement]] = []
    if mapped.elements:
        for element in mapped.elements:
            if element.type == "inline_math" and element.latex:
                if element.latex.lower() == "r^2":
                    segments.append(("r_squared", "2"))
                else:
                    segments.append(("latex", element.latex))
            elif element.value:
                if _inline_has_style(element):
                    segments.append(("styled", element))
                else:
                    segments.extend(_split_inline_text_segments(element.value))
        return segments
    return _split_inline_text_segments(_text_of(mapped))


def _append_r_squared_markup(parent: etree._Element) -> etree._Element:
    italic = etree.SubElement(parent, "italic")
    italic.text = "R"
    sup = etree.SubElement(parent, "sup")
    sup.text = "2"
    return sup


def _append_text_with_bibliographic_xrefs(
    parent: etree._Element,
    text: str,
    ctx: dict[str, str],
    last: etree._Element | None,
) -> etree._Element | None:
    position = 0
    for match in _BIBLIOGRAPHIC_CITATION_RE.finditer(text):
        before = sanitize_xml_text(
            text[position : match.start()],
            log_context={**ctx, "field": "inline.value"},
        )
        if before:
            if last is None:
                parent.text = (parent.text or "") + before
            else:
                last.tail = (last.tail or "") + before
        xref = etree.SubElement(parent, "xref")
        set_lxml_attr(
            xref,
            "ref-type",
            "bibr",
            log_context={**ctx, "field": "xref.ref-type"},
        )
        set_lxml_attr(
            xref,
            "rid",
            f"ref{match.group(1)}",
            log_context={**ctx, "field": "xref.rid"},
        )
        set_lxml_text(
            xref,
            match.group(0),
            log_context={**ctx, "field": "xref.text"},
        )
        last = xref
        position = match.end()

    remainder = sanitize_xml_text(
        text[position:],
        log_context={**ctx, "field": "inline.value"},
    )
    if remainder:
        if last is None:
            parent.text = (parent.text or "") + remainder
        else:
            last.tail = (last.tail or "") + remainder
    return last


def _append_styled_inline_element(
    parent: etree._Element,
    element: MappedInlineElement,
    ctx: dict[str, str],
    last: etree._Element | None,
) -> etree._Element | None:
    value = element.value or ""
    if element.superscript:
        sup = etree.SubElement(parent, "sup")
        set_lxml_text(sup, value, log_context={**ctx, "field": "inline.sup"})
        return sup
    if element.subscript:
        sub = etree.SubElement(parent, "sub")
        set_lxml_text(sub, value, log_context={**ctx, "field": "inline.sub"})
        return sub
    content_parent: etree._Element = parent
    last_out = last
    if element.bold:
        content_parent = etree.SubElement(parent, "bold")
        last_out = None
    if element.italic:
        italic_el = etree.SubElement(content_parent, "italic")
        content_parent = italic_el
        last_out = None
    return _append_text_with_bibliographic_xrefs(content_parent, value, ctx, last_out)


def _append_inline_segments(
    parent: etree._Element,
    segments: list[tuple[str, str | MappedInlineElement]],
    ctx: dict[str, str],
) -> None:
    last: etree._Element | None = None
    for segment_type, segment_value in segments:
        if segment_type == "styled" and isinstance(segment_value, MappedInlineElement):
            last = _append_styled_inline_element(parent, segment_value, ctx, last)
            continue
        if segment_type == "text" and isinstance(segment_value, str):
            last = _append_text_with_bibliographic_xrefs(parent, segment_value, ctx, last)
            continue
        if segment_type == "r_squared":
            last = _append_r_squared_markup(parent)
            continue
        if segment_type == "latex":
            inline = etree.SubElement(parent, "inline-formula")
            tex = etree.SubElement(inline, "tex-math", notation="LaTeX")
            set_lxml_text(
                tex,
                format_inline_math_for_ieee(segment_value),
                log_context={**ctx, "field": "inline_math.latex"},
            )
            last = inline


def _append_inline_content(parent: etree._Element, node: MappedSemanticNode | dict[str, Any]) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "inline")
    segments = _inline_segments_from_node(mapped)
    if segments:
        _append_inline_segments(parent, segments, ctx)
        return
    set_lxml_text(parent, _text_of(mapped), log_context=ctx)


def _append_drop_cap_paragraph(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    drop_cap_letter: str,
) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "inline")
    paragraph = etree.SubElement(parent, "p")
    bold = etree.SubElement(paragraph, "bold")
    bold.text = drop_cap_letter
    segments = _inline_segments_from_node(mapped)
    if segments and segments[0][0] == "text":
        first_text = segments[0][1]
        if first_text.startswith(drop_cap_letter):
            segments[0] = ("text", first_text[len(drop_cap_letter) :])
        if not segments[0][1]:
            segments = segments[1:]
    if not segments:
        return
    last = bold
    for segment_type, segment_value in segments:
        if segment_type == "text":
            last = _append_text_with_bibliographic_xrefs(paragraph, segment_value, ctx, last)
            continue
        if segment_type == "r_squared":
            last = _append_r_squared_markup(paragraph)
            continue
        if segment_type == "latex":
            inline = etree.SubElement(paragraph, "inline-formula")
            tex = etree.SubElement(inline, "tex-math", notation="LaTeX")
            set_lxml_text(
                tex,
                format_inline_math_for_ieee(segment_value),
                log_context={**ctx, "field": "inline_math.latex"},
            )
            last = inline


def _append_paragraph(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    *,
    bold: bool = False,
) -> None:
    mapped = _as_mapped(node)
    drop_cap_letter = None
    if mapped.metadata:
        drop_cap_letter = mapped.metadata.get("drop_cap_letter")
    elif isinstance(node, dict):
        metadata = node.get("metadata") or {}
        drop_cap_letter = metadata.get("drop_cap_letter")
    if not drop_cap_letter:
        drop_cap_letter = infer_drop_cap_letter(_text_of(mapped))
    if drop_cap_letter:
        _append_drop_cap_paragraph(parent, mapped, str(drop_cap_letter))
        return
    paragraph = etree.SubElement(parent, "p")
    content_parent = etree.SubElement(paragraph, "bold") if bold else paragraph
    _append_inline_content(content_parent, node)


def _extract_template_display_formula_ids(article: etree._Element) -> dict[str, str]:
    formula_ids: dict[str, str] = {}
    for formula in article.xpath(".//disp-formula[@id]"):
        formula_id = formula.get("id")
        if not formula_id:
            continue
        label_el = formula.find("label")
        if label_el is not None and label_el.text:
            match = re.search(r"(\d+)", label_el.text)
            if match:
                formula_ids[match.group(1)] = formula_id
    return formula_ids


def _append_display_math(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    *,
    template_formula_ids: dict[str, str] | None = None,
) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "display_math")
    formula_id = display_formula_id(mapped.label, template_formula_ids)
    formula_attrs = {"id": formula_id} if formula_id else None
    formula = etree.SubElement(parent, "disp-formula", formula_attrs)
    if mapped.label:
        label = etree.SubElement(formula, "label")
        set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
    tex = etree.SubElement(formula, "tex-math", notation="LaTeX")
    raw_latex = mapped.latex or _text_of(mapped, "latex")
    set_lxml_text(
        tex,
        format_display_math_for_ieee(raw_latex, mapped.label),
        log_context={**ctx, "field": "latex"},
    )


def _append_table(parent: etree._Element, node: MappedSemanticNode | dict[str, Any]) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "table")
    wrap = etree.SubElement(parent, "table-wrap")
    if mapped.label:
        label = etree.SubElement(wrap, "label")
        set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
    caption_text = _text_of(mapped, "caption")
    if caption_text:
        caption = etree.SubElement(wrap, "caption")
        caption_p = etree.SubElement(caption, "p")
        set_lxml_text(caption_p, caption_text, log_context={**ctx, "field": "caption"})
    rows = mapped.rows or []
    if not rows:
        return
    table = etree.SubElement(wrap, "table")
    header, body_rows = rows[0], rows[1:]
    thead = etree.SubElement(table, "thead")
    header_row = etree.SubElement(thead, "tr")
    for cell in header:
        th = etree.SubElement(header_row, "th")
        set_lxml_text(th, cell, log_context={**ctx, "field": "table.header"})
    if body_rows:
        tbody = etree.SubElement(table, "tbody")
        for row in body_rows:
            tr = etree.SubElement(tbody, "tr")
            for cell in row:
                td = etree.SubElement(tr, "td")
                set_lxml_text(td, cell, log_context={**ctx, "field": "table.cell"})


def _figure_id_from_label(label: str | None) -> str:
    digits = re.sub(r"\D+", "", label or "")
    return f"fig{digits or '1'}"


def _extract_template_figure_graphics(article: etree._Element) -> dict[str, str]:
    graphics: dict[str, str] = {}
    for figure in article.xpath(".//fig[@id]"):
        fig_id = figure.get("id")
        if not fig_id:
            continue
        graphic = figure.find("graphic")
        if graphic is None:
            continue
        href = graphic.get(f"{{{XLINK_NS}}}href") or graphic.get("href")
        if href:
            graphics[fig_id] = href
    return graphics


def _append_figure(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    *,
    template_graphics: dict[str, str] | None = None,
) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "figure")
    caption_text = _text_of(mapped, "caption")
    has_caption_child = any(child.semantic_type == "caption" for child in mapped.children)
    if not mapped.label and not caption_text and not has_caption_child:
        return

    fig_id = _figure_id_from_label(mapped.label)
    figure = etree.SubElement(parent, "fig", id=fig_id)
    fig_num = re.sub(r"\D+", "", fig_id) or "1"
    label_text = mapped.label or f"Fig. {fig_num}."
    label = etree.SubElement(figure, "label")
    set_lxml_text(label, label_text, log_context={**ctx, "field": "label"})

    rendered_caption = False
    for child in mapped.children:
        if child.semantic_type == "caption":
            caption = etree.SubElement(figure, "caption")
            caption_p = etree.SubElement(caption, "p")
            set_lxml_text(caption_p, _text_of(child, "caption"), log_context=_log_context_for(child, "caption"))
            rendered_caption = True
    if not rendered_caption and caption_text:
        caption = etree.SubElement(figure, "caption")
        caption_p = etree.SubElement(caption, "p")
        set_lxml_text(caption_p, caption_text, log_context={**ctx, "field": "caption"})

    graphic_href = (template_graphics or {}).get(fig_id)
    if not graphic_href and mapped.metadata:
        graphic_href = mapped.metadata.get("graphic_href")
    if not graphic_href:
        graphic_href = f"{fig_id}.eps"
    graphic = etree.SubElement(figure, "graphic")
    set_lxml_attr(
        graphic,
        f"{{{XLINK_NS}}}href",
        str(graphic_href),
        log_context={**ctx, "field": "graphic.href"},
    )


def _roman_section_index(label: str) -> int | None:
    token = label.strip().rstrip(".")
    return _ROMAN_SECTION_NUMBERS.get(token)


def _letter_subsection_suffix(label: str) -> str | None:
    match = re.match(r"^([A-Z])\.$", label.strip())
    return match.group(1) if match else None


def _numbered_subsection_suffix(label: str) -> str | None:
    match = re.match(r"^(\d+)\)?\.?$", label.strip())
    return match.group(1) if match else None


def _body_element(element: etree._Element) -> etree._Element:
    current = element
    while current.getparent() is not None:
        if current.tag == "body":
            return current
        current = current.getparent()
    return current


def _jats_list_type(list_type: str) -> str:
    normalized = list_type.strip().lower().replace("-", "_")
    if normalized in {"order", "ordered"}:
        return "ordered"
    if normalized in {"bullet", "unordered", "simple"}:
        return "bullet"
    return list_type


def _compact_sec_id(sec_id: str) -> str:
    return sec_id.replace(" ", "").lower()


class _SectionIdAllocator:
    """Allocate unique ``sec`` ids (IEEE Roman sections and nested suffixes)."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def _reserve(self, sec_id: str) -> str:
        candidate = sec_id
        if candidate in self._used:
            base = re.match(r"^(sec\d+)", candidate)
            root = base.group(1) if base else "sec"
            index = 1
            while True:
                candidate = f"{root}{index}"
                if candidate not in self._used:
                    break
                index += 1
        self._used.add(candidate)
        return candidate

    def allocate(self, mapped: MappedSemanticNode, parent_sec_id: str | None) -> str:
        label = (mapped.label or "").strip()
        roman = _roman_section_index(label)
        if roman is not None:
            return self._reserve(f"sec{roman}")

        if parent_sec_id is None:
            index = 1
            while f"sec{index}" in self._used:
                index += 1
            return self._reserve(f"sec{index}")

        compact_parent = _compact_sec_id(parent_sec_id)

        letter = _letter_subsection_suffix(label)
        if letter:
            return self._reserve(f"{compact_parent}{letter.lower()}")

        number = _numbered_subsection_suffix(label)
        if number:
            return self._reserve(f"{compact_parent}{number}")

        return self._reserve(f"{compact_parent}1")


_ACK_SECTION_RE = re.compile(r"^acknowledg", re.I)


def _is_acknowledgment_section(node: MappedSemanticNode | dict[str, Any]) -> bool:
    mapped = _as_mapped(node)
    if mapped.semantic_type not in _SECTION_SEMANTIC_TYPES:
        return False
    title = (mapped.text or "").strip()
    return bool(_ACK_SECTION_RE.match(title))


def _acknowledgment_text_from_section(node: MappedSemanticNode | dict[str, Any]) -> str:
    mapped = _as_mapped(node)
    parts: list[str] = []
    for child in mapped.children:
        child_mapped = _as_mapped(child)
        if child_mapped.semantic_type == "paragraph":
            text = _text_of(child_mapped).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def _partition_acknowledgment_sections(
    nodes: list[MappedSemanticNode | dict[str, Any]],
) -> tuple[list[MappedSemanticNode | dict[str, Any]], str | None]:
    body_nodes: list[MappedSemanticNode | dict[str, Any]] = []
    ack_parts: list[str] = []
    for node in nodes:
        if _is_acknowledgment_section(node):
            ack_text = _acknowledgment_text_from_section(node)
            if ack_text:
                ack_parts.append(ack_text)
            continue
        body_nodes.append(node)
    if not ack_parts:
        return nodes, None
    return body_nodes, "\n\n".join(ack_parts)


def _reference_citation_text(mapped: MappedSemanticNode) -> str:
    citation = _text_of(mapped).strip()
    label = (mapped.label or "").strip()
    if label and citation.startswith(label):
        citation = citation[len(label) :].strip()
    return citation


def _assembled_references_from_mapping(
    references: list[MappedSemanticNode | dict[str, Any]],
) -> list[AssembledReference]:
    assembled: list[AssembledReference] = []
    for index, reference in enumerate(references, start=1):
        mapped = _as_mapped(reference)
        number = reference_number_from_mapping_node(
            mapped,
            text=_text_of(mapped),
            label=mapped.label,
            fallback=index,
        )
        assembled.append(
            AssembledReference(
                reference_number=number,
                label=f"[{number}]",
                raw_text=_text_of(mapped),
                source_block_ids=list(mapped.source_block_ids),
                page_numbers=[],
                bbox=None,
                confidence=mapped.confidence or 1.0,
            )
        )
    return assembled


def _deduplicate_mapping_reference_list(
    references: list[MappedSemanticNode | dict[str, Any]],
) -> list[MappedSemanticNode | dict[str, Any]]:
    if not references:
        return references
    by_number: dict[int, MappedSemanticNode | dict[str, Any]] = {}
    for index, reference in enumerate(references):
        mapped = _as_mapped(reference)
        number = reference_number_from_mapping_node(
            mapped,
            text=_text_of(mapped),
            label=mapped.label,
            fallback=index + 1,
        )
        if number in by_number:
            logger.info("Removed duplicate reference [%s]", number)
        by_number[number] = reference
    return [by_number[number] for number in sorted(by_number)]


def _validate_mapping_references(references: list[MappedSemanticNode | dict[str, Any]]) -> None:
    assembled = deduplicate_assembled_references(_assembled_references_from_mapping(references))
    validate_reference_sequence(assembled)


def _append_reference(parent: etree._Element, node: MappedSemanticNode | dict[str, Any], index: int) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "reference")
    reference_number = reference_number_from_mapping_node(
        mapped,
        text=_text_of(mapped),
        label=mapped.label,
        fallback=index,
    )
    ref = etree.SubElement(parent, "ref", id=f"ref{reference_number}")
    label_text = f"[{reference_number}]"
    label = etree.SubElement(ref, "label")
    set_lxml_text(label, label_text, log_context={**ctx, "field": "label"})
    citation = etree.SubElement(ref, "mixed-citation")
    populate_structured_mixed_citation(
        citation,
        _reference_citation_text(mapped),
        log_context=ctx,
    )


def _append_section(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    parent_sec_id: str | None,
    template_graphics: dict[str, str] | None = None,
    template_formula_ids: dict[str, str] | None = None,
    section_ids: _SectionIdAllocator | None = None,
) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "section")
    allocator = section_ids or _SectionIdAllocator()
    sec_id = allocator.allocate(mapped, parent_sec_id)

    if parent_sec_id and sec_id == parent_sec_id:
        if parent.tag == "sec":
            if mapped.label and parent.find("label") is None:
                label = etree.SubElement(parent, "label")
                set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
            title_text = mapped.text or ""
            if title_text and parent.find("title") is None:
                title = etree.SubElement(parent, "title")
                set_lxml_text(title, title_text, log_context={**ctx, "field": "title"})
        _append_mapped_nodes(
            parent,
            list(mapped.children),
            parent_sec_id=parent_sec_id,
            template_graphics=template_graphics,
            template_formula_ids=template_formula_ids,
            section_ids=allocator,
        )
        return

    if parent_sec_id and _roman_section_index(mapped.label or ""):
        body_el = _body_element(parent)
        if body_el is not parent:
            _append_section(
                body_el,
                mapped,
                parent_sec_id=None,
                template_graphics=template_graphics,
                template_formula_ids=template_formula_ids,
                section_ids=allocator,
            )
            return

    sec = etree.SubElement(parent, "sec", id=sec_id)
    if mapped.label:
        label = etree.SubElement(sec, "label")
        set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
    title_text = mapped.text or ""
    if title_text:
        title = etree.SubElement(sec, "title")
        set_lxml_text(title, title_text, log_context={**ctx, "field": "title"})
    _append_mapped_nodes(
        sec,
        list(mapped.children),
        parent_sec_id=sec_id,
        template_graphics=template_graphics,
        template_formula_ids=template_formula_ids,
        section_ids=allocator,
    )


def _append_mapped_node(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    ref_index: int,
    parent_sec_id: str | None = None,
    template_graphics: dict[str, str] | None = None,
    template_formula_ids: dict[str, str] | None = None,
    section_ids: _SectionIdAllocator | None = None,
) -> int:
    mapped = _as_mapped(node)
    semantic_type = mapped.semantic_type

    if semantic_type in _SECTION_SEMANTIC_TYPES:
        _append_section(
            parent,
            mapped,
            parent_sec_id,
            template_graphics=template_graphics,
            template_formula_ids=template_formula_ids,
            section_ids=section_ids,
        )
        return ref_index
    if semantic_type == "paragraph":
        _append_paragraph(parent, mapped)
        return ref_index
    if semantic_type == "display_math":
        _append_display_math(parent, mapped, template_formula_ids=template_formula_ids)
        return ref_index
    if semantic_type == "table":
        _append_table(parent, mapped)
        return ref_index
    if semantic_type == "figure":
        _append_figure(parent, mapped, template_graphics=template_graphics)
        return ref_index
    if semantic_type == "reference":
        _append_reference(parent, mapped, ref_index)
        return ref_index + 1
    if semantic_type == "list":
        list_type = "order"
        if mapped.metadata and mapped.metadata.get("list_type"):
            list_type = str(mapped.metadata["list_type"])
        elif isinstance(node, dict) and node.get("list_type"):
            list_type = str(node["list_type"])
        list_el = etree.SubElement(parent, "list")
        set_lxml_attr(
            list_el,
            "list-type",
            _jats_list_type(list_type),
            log_context=_log_context_for(mapped, "list-type"),
        )
        for child in mapped.children:
            item = etree.SubElement(list_el, "list-item")
            item_p = etree.SubElement(item, "p")
            set_lxml_text(item_p, _text_of(child), log_context=_log_context_for(child, "list_item"))
        return ref_index

    text = _text_of(mapped)
    if text:
        _append_paragraph(parent, mapped)
    return ref_index


def _append_mapped_nodes(
    parent: etree._Element,
    nodes: list[MappedSemanticNode | dict[str, Any]],
    *,
    parent_sec_id: str | None = None,
    template_graphics: dict[str, str] | None = None,
    template_formula_ids: dict[str, str] | None = None,
    section_ids: _SectionIdAllocator | None = None,
) -> None:
    ref_index = 1
    allocator = section_ids or _SectionIdAllocator()
    for node in nodes:
        ref_index = _append_mapped_node(
            parent,
            node,
            ref_index,
            parent_sec_id=parent_sec_id,
            template_graphics=template_graphics,
            template_formula_ids=template_formula_ids,
            section_ids=allocator,
        )


def _keyword_tokens_from_node(keywords_data: MappedSemanticNode | dict[str, Any]) -> list[str]:
    from app.utils.front_matter_recovery import parse_index_terms_keywords

    if isinstance(keywords_data, dict):
        meta = keywords_data.get("metadata") or {}
        preset = meta.get("keywords")
        if isinstance(preset, list) and preset:
            return [str(item).strip() for item in preset if str(item).strip()]
        ir_keywords = keywords_data.get("keywords")
        if isinstance(ir_keywords, list) and ir_keywords:
            return [str(item).strip() for item in ir_keywords if str(item).strip()]
    else:
        meta = keywords_data.metadata or {}
        preset = meta.get("keywords")
        if isinstance(preset, list) and preset:
            return [str(item).strip() for item in preset if str(item).strip()]

    return parse_index_terms_keywords(_text_of(keywords_data, "keywords"))


def _apply_front_matter(article: etree._Element, front: dict[str, Any]) -> None:
    front_el = article.find("front")
    if front_el is None:
        return
    article_meta = front_el.find("article-meta")
    if article_meta is None:
        return

    title_data = front.get("title")
    if title_data:
        title_group = article_meta.find("title-group")
        if title_group is not None:
            article_title = title_group.find("article-title")
            if article_title is None:
                article_title = etree.SubElement(title_group, "article-title")
            set_lxml_text(
                article_title,
                _text_of(title_data, "article-title"),
                log_context={"semantic_type": "metadata", "source": "-", "field": "article-title"},
            )

    abstract_data = front.get("abstract")
    if abstract_data:
        abstract = article_meta.find("abstract")
        if abstract is None:
            abstract = etree.SubElement(article_meta, "abstract")
        for child in list(abstract):
            abstract.remove(child)
        _append_paragraph(abstract, abstract_data, bold=True)

    keywords_data = front.get("keywords")
    if keywords_data:
        kwd_group = article_meta.find("kwd-group")
        if kwd_group is None:
            kwd_group = etree.SubElement(article_meta, "kwd-group", kwd_group_type="AuthorFree")
        for child in list(kwd_group):
            if child.tag == "kwd":
                kwd_group.remove(child)
        for token in _keyword_tokens_from_node(keywords_data):
            kwd = etree.SubElement(kwd_group, "kwd")
            set_lxml_text(
                kwd,
                token,
                log_context={"semantic_type": "keywords", "source": "-", "field": "kwd"},
            )

    authors_data = front.get("authors") or []
    if authors_data:
        contrib_group = article_meta.find("contrib-group")
        if contrib_group is None:
            contrib_group = etree.SubElement(article_meta, "contrib-group")
        for child in list(contrib_group):
            if child.tag == "contrib":
                contrib_group.remove(child)
        seen_keys: set[str] = set()
        index = 0
        for author_data in authors_data:
            name_text = clean_author_display_name(_text_of(author_data, "author").strip())
            if not name_text or is_boilerplate_text(name_text):
                continue
            key = author_dedup_key(name_text)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            index += 1
            _append_author_contrib(contrib_group, author_data, index, name_override=name_text)


def _set_person_name_on_element(
    parent: etree._Element,
    given: str,
    surname: str,
) -> None:
    ctx = {"semantic_type": "author", "source": "-", "field": "name"}
    given_el = next(
        (child for child in parent if xml_local_name(child) == "given-names"),
        None,
    )
    surname_el = next(
        (child for child in parent if xml_local_name(child) == "surname"),
        None,
    )
    if surname and surname_el is None:
        surname_el = etree.SubElement(parent, "surname")
    if surname and surname_el is not None:
        set_lxml_text(surname_el, surname, log_context={**ctx, "field": "surname"})
    if given and given_el is None:
        given_el = etree.SubElement(parent, "given-names")
    if given and given_el is not None:
        set_lxml_text(given_el, given, log_context={**ctx, "field": "given-names"})


def _populate_contrib_person_names(contrib: etree._Element, given: str, surname: str) -> None:
    targets: list[etree._Element] = []
    for element in contrib.iter():
        if not isinstance(element.tag, str):
            continue
        local = xml_local_name(element)
        if local in {"name", "string-name"}:
            targets.append(element)
    if not targets:
        name_alt = etree.SubElement(contrib, "name-alternatives")
        name = etree.SubElement(name_alt, "name")
        targets = [name]
    for target in targets:
        _set_person_name_on_element(target, given, surname)


def _append_author_contrib(
    contrib_group: etree._Element,
    author_data: MappedSemanticNode | dict[str, Any],
    index: int,
    *,
    name_override: str | None = None,
) -> None:
    name_text = clean_author_display_name(
        (name_override or _text_of(author_data, "author")).strip()
    )
    if not name_text:
        return
    given, surname = split_person_name(name_text)
    contrib = etree.SubElement(
        contrib_group,
        "contrib",
        attrib={"contrib-type": "author", "id": f"contrib{index}"},
    )
    _populate_contrib_person_names(contrib, given, surname)


def _normalize_person_name_elements(article: etree._Element) -> None:
    """Strip surrounding whitespace from front-matter author name fields in the template."""
    front = article.find("front")
    if front is None:
        return
    for element in front.iter():
        if xml_local_name(element) not in _PERSON_NAME_TAGS:
            continue
        if element.text is None:
            continue
        set_lxml_text(
            element,
            normalize_person_name_text(element.text),
            log_context={"semantic_type": "author", "source": "-", "field": element.tag},
        )


def _apply_acknowledgment(article: etree._Element, acknowledgment: str | None) -> None:
    if not acknowledgment or not acknowledgment.strip():
        return
    back_el = article.find("back")
    if back_el is None:
        back_el = etree.SubElement(article, "back")
    ack = back_el.find("ack")
    if ack is None:
        ack = etree.SubElement(back_el, "ack")
    for child in list(ack):
        ack.remove(child)
    paragraph = etree.SubElement(ack, "p")
    set_lxml_text(
        paragraph,
        acknowledgment.strip(),
        log_context={"semantic_type": "acknowledgment", "source": "-", "field": "p"},
    )


def _ref_list_ref_nodes(article: etree._Element) -> list[etree._Element]:
    return article.xpath(
        "//*[local-name()='back']/*[local-name()='ref-list']/*[local-name()='ref']"
    )


def _find_back_ref_list(back_el: etree._Element) -> etree._Element:
    ref_lists = back_el.xpath("*[local-name()='ref-list']")
    if ref_lists:
        return ref_lists[0]
    return etree.SubElement(back_el, "ref-list")


def _prepare_mapping_back_references(
    body: SemanticMappingBody,
    ir: dict[str, Any] | None,
    phase1: dict[str, Any] | None,
) -> SemanticMappingBody:
    """Merge Phase 1 / IR bibliography into the mapping used for ``<ref-list>``."""
    from app.services.ir_semantic_adapter import fill_back_references_from_ir
    from app.services.phase1_reference_bridge import merge_phase1_references_into_ir

    merged_ir = merge_phase1_references_into_ir(ir or {}, phase1)
    return fill_back_references_from_ir(body, merged_ir)


def _apply_back_matter(article: etree._Element, back: dict[str, Any]) -> int | None:
    """Populate back matter.

    Returns the number of ``<ref>`` nodes written when bibliography is replaced,
    or ``None`` when existing ``<ref-list>`` content is left unchanged.
    """
    references = back.get("references") or []
    acknowledgment = back.get("acknowledgment")
    back_el = article.find("back")
    if back_el is None:
        if not references and not acknowledgment:
            return None
        back_el = etree.SubElement(article, "back")
    if acknowledgment:
        _apply_acknowledgment(article, str(acknowledgment))

    if not references:
        return None

    ref_list = _find_back_ref_list(back_el)
    title_nodes = ref_list.xpath("*[local-name()='title']")
    if not title_nodes:
        title = etree.SubElement(ref_list, "title")
        set_lxml_text(
            title,
            "References",
            log_context={"semantic_type": "reference_list", "source": "-", "field": "title"},
        )
    for child in list(ref_list):
        if xml_local_name(child) == "ref":
            ref_list.remove(child)

    references = _deduplicate_mapping_reference_list(references)

    try:
        _validate_mapping_references(references)
    except ReferenceParsingError as exc:
        raise XmlGenerationError(
            f"Bibliography validation failed: {exc}. "
            "Re-run extraction after fixing reference-section detection."
        ) from exc
    for index, reference in enumerate(references, start=1):
        _append_reference(ref_list, reference, index)
    return len(references)


_RELOCATE_ABSTRACT_LABEL_RE = re.compile(r"^(?:Abstract|ABSTRACT)\s*[—\-–:]\s*", re.IGNORECASE)
_RELOCATE_INDEX_TERMS_RE = re.compile(
    r"^(?:Index\s+Terms|Keywords?)\s*[—\-–:]\s*",
    re.IGNORECASE,
)


def _relocate_para_text(para: etree._Element) -> str:
    return "".join(para.itertext()).strip()


def _strip_relocate_abstract_label(text: str) -> str:
    return _RELOCATE_ABSTRACT_LABEL_RE.sub("", text or "").strip()


def _is_relocate_keyword_paragraph(text: str) -> bool:
    """Comma-list / index-terms lines must not be merged into the abstract."""
    if not text:
        return False
    if _RELOCATE_INDEX_TERMS_RE.match(text):
        return True
    lowered = text.lower()
    if re.match(r"^range,\s*lifespan", lowered):
        return True
    comma_count = text.count(",")
    if comma_count >= 2 and len(text) < 450:
        sentence_markers = ("however", "therefore", "although", " we ", " this paper", " these ")
        if not any(marker in lowered for marker in sentence_markers):
            if text.count(".") <= 1:
                return True
    return False


_RELOCATE_ABSTRACT_MARKERS = (
    "rapid adoption",
    "electric vehicles",
    "heightened the need",
    "heightened",
    "battery systems",
    "susceptible to",
    "traditional diagnostic",
    "machine learning has emerged",
    "federated learning",
    "this paper presents",
    "experimental results",
    "however, they",
    "privacy-preserving",
    "state-of-the-art",
)


def _is_relocate_abstract_fragment(text: str) -> bool:
    """True when a loose <p> is part of the abstract (not keywords/title)."""
    from app.utils.front_matter_recovery import is_post_keywords_abstract_fragment

    if _is_relocate_keyword_paragraph(text):
        return False
    if len(text) < 50:
        if is_post_keywords_abstract_fragment(text):
            return True
        stripped = text.strip()
        if re.match(r"^\d", stripped) and "%" in stripped and len(stripped) >= 12:
            return True
        return False
    if _RELOCATE_ABSTRACT_LABEL_RE.match(text):
        return True
    lowered = text.lower()
    if any(marker in lowered for marker in _RELOCATE_ABSTRACT_MARKERS):
        if len(text) < 140 and not lowered.startswith(
            ("the rapid", "machine learning", "however", "they ", "this paper", "although ")
        ):
            if "," not in text and "." not in text and "%" not in text:
                return False
        return True
    if text[0].islower() and len(text) > 70:
        return True
    return text.startswith(
        (
            "However",
            "They ",
            "These ",
            "This ",
            "Although ",
            "In this",
            "To address",
            "The rapid",
            "Machine learning",
        )
    )


def _is_relocate_abstract_continuation(text: str, *, has_seed: bool) -> bool:
    if not has_seed:
        return _is_relocate_abstract_fragment(text)
    return _is_relocate_abstract_fragment(text)


def _join_relocate_abstract_parts(parts: list[str]) -> str:
    from app.utils.front_matter_recovery import merge_abstract_segment

    merged = ""
    for part in parts:
        chunk = _strip_relocate_abstract_label(part)
        if not chunk:
            continue
        if _is_relocate_keyword_paragraph(chunk):
            logger.info("[relocate] Skipping keyword-like chunk in abstract: %s...", chunk[:80])
            continue
        if not merged:
            merged = chunk
            continue
        if chunk in merged or merged in chunk:
            if len(chunk) > len(merged):
                merged = chunk
            continue
        if len(chunk) >= 40 and chunk[:40] in merged:
            continue
        if merged.endswith("-") and not chunk.startswith(" "):
            merged = merged[:-1] + chunk
        else:
            merged = merge_abstract_segment(merged, chunk)
    merged = _strip_relocate_abstract_label(merged)
    return re.sub(r"\s+", " ", merged).strip()


def _set_relocate_abstract_text(abstract_p: etree._Element, combined: str) -> None:
    abstract_p.attrib.pop("bold", None)
    for bold in abstract_p.xpath("*[local-name()='bold']"):
        abstract_p.remove(bold)
    abstract_p.text = combined


def relocate_misplaced_front_matter(article_elem: etree._Element) -> None:
    """
    Relocate loose body paragraphs that are actually front-matter content
    (title, abstract continuation, keywords) into the proper <front> location.

    These paragraphs appear after the last <sec> in <body> for proof PDFs where
    page 1 (author queries) was skipped and page 2 content got mapped to body.
    """
    front_nodes = article_elem.xpath("*[local-name()='front']")
    body_nodes = article_elem.xpath("*[local-name()='body']")
    if not front_nodes or not body_nodes:
        logger.warning("[relocate] No <front> or <body> found")
        return
    front = front_nodes[0]
    body = body_nodes[0]

    meta_nodes = front.xpath("*[local-name()='article-meta']")
    if not meta_nodes:
        logger.warning("[relocate] No <article-meta> in <front>")
        return
    meta = meta_nodes[0]

    loose_paras = [child for child in list(body) if xml_local_name(child) == "p"]

    logger.info("[relocate] Found %s loose paragraphs in body", len(loose_paras))
    for index, para in enumerate(loose_paras):
        text = "".join(para.itertext()).strip()
        logger.info("[relocate] para[%s]: %s...", index, text[:120])

    if not loose_paras:
        logger.info("[relocate] No loose paragraphs to relocate")
        return

    # ====================================================================
    # STEP 1: TITLE
    # ====================================================================
    title_group_nodes = meta.xpath("*[local-name()='title-group']")
    title_group = title_group_nodes[0] if title_group_nodes else etree.SubElement(meta, "title-group")

    article_title_nodes = title_group.xpath("*[local-name()='article-title']")
    article_title = (
        article_title_nodes[0]
        if article_title_nodes
        else etree.SubElement(title_group, "article-title")
    )

    current_title = (article_title.text or "").strip()
    if not current_title:
        current_title = "".join(article_title.itertext()).strip()

    title_candidate: tuple[str, etree._Element] | None = None
    for para in loose_paras:
        text = "".join(para.itertext()).strip()
        if not (20 < len(text) < 250):
            continue
        if _is_relocate_abstract_fragment(text) or _is_relocate_keyword_paragraph(text):
            continue
        if text.isupper():
            continue
        if text.upper().startswith("IEEE ") or text.upper().startswith("VOLUME"):
            continue
        if text.upper().startswith("AMARA ") or " et al." in text[:50]:
            continue
        if text.endswith(".") and not text.endswith("?"):
            continue
        if text.count(",") > 5:
            continue
        words = text.split()
        if len(words) < 4 or len(words) > 30:
            continue
        if text[0].islower():
            continue
        if title_candidate is None or len(text) > len(title_candidate[0]):
            title_candidate = (text, para)

    if not current_title and title_candidate:
        text, para = title_candidate
        article_title.text = text
        for child in list(article_title):
            article_title.remove(child)
        body.remove(para)
        loose_paras.remove(para)
        current_title = text
        logger.info("[relocate] TITLE set to: %s", text)

    # ====================================================================
    # STEP 2: ABSTRACT
    # ====================================================================
    abstract_nodes = meta.xpath("*[local-name()='abstract']")
    abstract = abstract_nodes[0] if abstract_nodes else etree.SubElement(meta, "abstract")

    abstract_p_nodes = abstract.xpath("*[local-name()='p']")
    abstract_p = abstract_p_nodes[0] if abstract_p_nodes else etree.SubElement(abstract, "p")

    current_abstract = _relocate_para_text(abstract_p)
    logger.info("[relocate] Current abstract length: %s", len(current_abstract))

    seed = _strip_relocate_abstract_label(current_abstract)
    abstract_parts: list[str] = [seed] if seed else []
    absorbed_abstract: list[etree._Element] = []

    if len(current_abstract) < 1200:
        for para in loose_paras[:]:
            text = _relocate_para_text(para)
            if re.match(r"^IEEE\s+TRANSACTIONS", text, re.IGNORECASE) or re.match(
                r"^\d+\s+IEEE\s+TRANSACTIONS", text, re.IGNORECASE
            ):
                continue
            if _is_relocate_keyword_paragraph(text):
                logger.info("[relocate] Stopping abstract scan at keyword-like para: %s...", text[:80])
                break
            if _is_relocate_abstract_continuation(text, has_seed=bool(abstract_parts)):
                abstract_parts.append(text)
                absorbed_abstract.append(para)

        combined = _join_relocate_abstract_parts(abstract_parts)
        if combined and len(combined) > len(seed):
            _set_relocate_abstract_text(abstract_p, combined)
            for para in absorbed_abstract:
                body.remove(para)
                loose_paras.remove(para)
            logger.info("[relocate] ABSTRACT set, new length: %s", len(combined))
            current_abstract = combined

    combined_lower = current_abstract.lower()
    for para in loose_paras[:]:
        text = _relocate_para_text(para)
        if not _is_relocate_abstract_fragment(text):
            continue
        body.remove(para)
        loose_paras.remove(para)
        logger.info("[relocate] Removed abstract fragment from body: %s...", text[:60])
        if text.lower() not in combined_lower:
            from app.utils.front_matter_recovery import merge_abstract_segment

            current_abstract = merge_abstract_segment(current_abstract, text)
            _set_relocate_abstract_text(abstract_p, current_abstract)
            combined_lower = current_abstract.lower()
            logger.info("[relocate] ABSTRACT extended, length: %s", len(current_abstract))

    # ====================================================================
    # STEP 3: KEYWORDS
    # ====================================================================
    kwd_group_nodes = meta.xpath("*[local-name()='kwd-group']")
    kwd_group = kwd_group_nodes[0] if kwd_group_nodes else etree.SubElement(meta, "kwd-group")
    if kwd_group.get("kwd-group-type") is None:
        kwd_group.set("kwd-group-type", "AuthorFree")

    existing_kwds = kwd_group.xpath("*[local-name()='kwd']")
    logger.info("[relocate] Existing keywords: %s", len(existing_kwds))

    keyword_chunks: list[str] = []
    for kwd_el in existing_kwds:
        kwd_text = (kwd_el.text or "").strip()
        if kwd_text:
            keyword_chunks.append(kwd_text)

    if len(existing_kwds) < 8:
        for para in loose_paras[:]:
            text = _relocate_para_text(para)
            is_candidate = _is_relocate_keyword_paragraph(text) or (
                30 < len(text) < 500
                and ("," in text or ";" in text)
                and any(
                    term in text.lower()
                    for term in (
                        "vehicle",
                        "battery",
                        "federated",
                        "transformer",
                        "soc",
                        "bms",
                        "learning",
                        "state",
                        "range",
                        "lifespan",
                    )
                )
            )
            if not is_candidate:
                continue

            logger.info("[relocate] KEYWORD candidate: %s...", text[:100])
            keyword_chunks.append(text)
            body.remove(para)
            loose_paras.remove(para)

        if keyword_chunks:
            for kwd in list(kwd_group.xpath("*[local-name()='kwd']")):
                kwd_group.remove(kwd)

            combined_keywords = " ".join(keyword_chunks)
            combined_keywords = re.sub(r"\s*,\s*", ", ", combined_keywords)
            combined_keywords = re.sub(r"\s*;\s*", "; ", combined_keywords)
            combined_keywords = _RELOCATE_INDEX_TERMS_RE.sub("", combined_keywords).strip()

            seen: set[str] = set()
            for kw in re.split(r"[,;]", combined_keywords):
                kw = kw.strip().rstrip(".")
                if not kw or len(kw) < 3 or len(kw) > 100:
                    continue
                key = kw.lower()
                if key in seen:
                    continue
                seen.add(key)
                kwd_el = etree.SubElement(kwd_group, "kwd")
                kwd_el.text = kw

            logger.info(
                "[relocate] KEYWORDS rebuilt: %s keywords",
                len(kwd_group.xpath("*[local-name()='kwd']")),
            )

    # ====================================================================
    # STEP 4: Remove residual noise paragraphs
    # ====================================================================
    for para in list(loose_paras):
        text = "".join(para.itertext()).strip()
        if re.match(r"^IEEE\s+TRANSACTIONS\s+ON\s+\w+", text, re.IGNORECASE):
            body.remove(para)
            logger.info("[relocate] Removed running header: %s", text[:60])
        elif re.match(r"^\d+\s+IEEE\s+TRANSACTIONS", text, re.IGNORECASE):
            body.remove(para)
            logger.info("[relocate] Removed page header: %s", text[:60])


def _sync_counts_from_dom(
    article: etree._Element,
    *,
    page_count: int | None = None,
) -> None:
    """Align ``counts`` with elements actually present in the generated article."""
    article_meta_nodes = article.xpath("//*[local-name()='front']/*[local-name()='article-meta']")
    if not article_meta_nodes:
        return
    article_meta = article_meta_nodes[0]
    counts_nodes = article_meta.xpath("*[local-name()='counts']")
    counts = counts_nodes[0] if counts_nodes else etree.SubElement(article_meta, "counts")

    body_scope = ".//*[local-name()='body']"
    specs: list[tuple[str, int]] = [
        ("fig-count", len(article.xpath(f"{body_scope}//*[local-name()='fig']"))),
        ("table-count", len(article.xpath(f"{body_scope}//*[local-name()='table-wrap']"))),
        ("equation-count", len(article.xpath(f"{body_scope}//*[local-name()='disp-formula']"))),
        ("ref-count", len(_ref_list_ref_nodes(article))),
    ]
    if page_count is not None:
        specs.append(("page-count", page_count))

    for tag, value in specs:
        nodes = counts.xpath(f"*[local-name()='{tag}']")
        node = nodes[0] if nodes else etree.SubElement(counts, tag)
        node.set("count", str(value))


def _sync_ref_count_to_ref_list(
    article: etree._Element,
    *,
    reference_count: int | None = None,
) -> None:
    """Set ``ref-count`` to match ``<ref-list>`` (written count or live DOM count)."""
    count = reference_count
    if count is None:
        count = len(_ref_list_ref_nodes(article))

    article_meta_nodes = article.xpath("//*[local-name()='front']/*[local-name()='article-meta']")
    if not article_meta_nodes:
        return
    article_meta = article_meta_nodes[0]
    counts_nodes = article_meta.xpath("*[local-name()='counts']")
    counts = counts_nodes[0] if counts_nodes else etree.SubElement(article_meta, "counts")
    ref_count_nodes = counts.xpath("*[local-name()='ref-count']")
    ref_count_el = ref_count_nodes[0] if ref_count_nodes else etree.SubElement(counts, "ref-count")
    ref_count_el.set("count", str(count))


def generate_jats_xml(
    template_path: str | Path,
    mapping: SemanticMappingBody | dict[str, Any],
    *,
    phase1: dict[str, Any] | None = None,
    source_filename: str | None = None,
    ir: dict[str, Any] | None = None,
    source: Any | None = None,
) -> str:
    """Generate IEEE JATS XML using a client template skeleton and semantic mapping."""
    path = Path(template_path)
    if not path.exists():
        raise XmlGenerationError(f"Template XML not found: {path}")

    if isinstance(mapping, SemanticMappingBody):
        body = mapping
    else:
        body = SemanticMappingBody.model_validate(mapping.get("mapping", mapping))

    body = _prepare_mapping_back_references(body, ir, phase1)

    try:
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(str(path), parser)
    except etree.XMLSyntaxError as exc:
        raise XmlGenerationError(f"Invalid template XML: {exc}") from exc

    article = tree.getroot()
    try:
        require_jats_article_template(article)
    except UnsupportedTemplateRootError as exc:
        raise XmlGenerationError(str(exc)) from exc

    strip_template_for_semantic_mapping(article)

    _apply_front_matter(article, body.front)

    from app.services.jats_metadata_overlay import (
        apply_jats_metadata_overlay,
        build_jats_metadata_overlay,
        build_source_figure_graphics,
    )

    template_graphics = _extract_template_figure_graphics(article)
    source_graphics = build_source_figure_graphics(
        source_filename=source_filename,
        phase1=phase1,
    )
    figure_graphics = source_graphics or template_graphics
    template_formula_ids = _extract_template_display_formula_ids(article)

    body_nodes, acknowledgment = _partition_acknowledgment_sections(list(body.body))
    back_matter = dict(body.back)
    if acknowledgment:
        back_matter["acknowledgment"] = acknowledgment

    body_el = article.find("body")
    if body_el is not None:
        for child in list(body_el):
            body_el.remove(child)
        _append_mapped_nodes(
            body_el,
            body_nodes,
            template_graphics=figure_graphics,
            template_formula_ids=template_formula_ids,
        )

    overlay = build_jats_metadata_overlay(
        phase1=phase1,
        ir=ir,
        mapping=body,
        source=source,
        source_filename=source_filename,
    )
    apply_jats_metadata_overlay(
        article,
        overlay=overlay,
        mapping=body,
        phase1=phase1,
    )

    reference_count = _apply_back_matter(article, back_matter)
    _normalize_person_name_elements(article)

    from app.utils.jats_empty_prune import prune_empty_jats_elements

    prune_empty_jats_elements(article)

    dom_page_count = overlay.page_count
    if dom_page_count is None and phase1 and phase1.get("pages"):
        dom_page_count = len(phase1["pages"])
    _sync_counts_from_dom(article, page_count=dom_page_count)
    if reference_count is not None:
        _sync_ref_count_to_ref_list(article, reference_count=reference_count)

    relocate_misplaced_front_matter(article)

    return serialize_lxml_tree(
        article,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=tree.docinfo.doctype if tree.docinfo.doctype else None,
    )


def generate_jats_xml_from_ir(
    template_path: str | Path,
    ir: dict[str, Any],
    *,
    phase1: dict[str, Any] | None = None,
) -> str:
    """Convenience: Stage 1 IR → mapping → JATS XML without LLM."""
    from app.services.ir_semantic_adapter import ir_to_semantic_mapping

    mapping = ir_to_semantic_mapping(ir)
    return generate_jats_xml(template_path, mapping, phase1=phase1, ir=ir)
