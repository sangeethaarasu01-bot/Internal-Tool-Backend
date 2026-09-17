"""Phase 3: template-driven JATS XML generation from semantic mapping JSON.

The LLM produces structured mapping JSON; this module deterministically renders
IEEE JATS XML using the uploaded client template as the structural skeleton.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.utils.math_latex import (
    display_formula_id,
    format_display_math_for_ieee,
    format_inline_math_for_ieee,
)
from app.utils.text_utils import dehyphenate_line_breaks, infer_drop_cap_letter
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


def _inline_segments_from_node(mapped: MappedSemanticNode) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    if mapped.elements:
        for element in mapped.elements:
            if element.type == "inline_math" and element.latex:
                if element.latex.lower() == "r^2":
                    segments.append(("r_squared", "2"))
                else:
                    segments.append(("latex", element.latex))
            elif element.value:
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


def _append_inline_segments(
    parent: etree._Element,
    segments: list[tuple[str, str]],
    ctx: dict[str, str],
) -> None:
    last: etree._Element | None = None
    for segment_type, segment_value in segments:
        if segment_type == "text":
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


def _make_section_id(mapped: MappedSemanticNode, parent_sec_id: str | None) -> str:
    label = (mapped.label or "").strip()
    roman = _roman_section_index(label)
    if roman is not None:
        return f"sec{roman}"

    if parent_sec_id is None:
        return "sec1"

    compact_parent = _compact_sec_id(parent_sec_id)

    letter = _letter_subsection_suffix(label)
    if letter:
        return f"{compact_parent}{letter.lower()}"

    number = _numbered_subsection_suffix(label)
    if number:
        return f"{compact_parent}{number}"

    return f"{compact_parent}1"


def _reference_citation_text(mapped: MappedSemanticNode) -> str:
    citation = _text_of(mapped).strip()
    label = (mapped.label or "").strip()
    if label and citation.startswith(label):
        citation = citation[len(label) :].strip()
    return citation


def _append_reference(parent: etree._Element, node: MappedSemanticNode | dict[str, Any], index: int) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "reference")
    ref = etree.SubElement(parent, "ref", id=f"ref{index}")
    label_text = mapped.label or f"[{index}]"
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
) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "section")
    sec_id = _make_section_id(mapped, parent_sec_id)

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
    )


def _append_mapped_node(
    parent: etree._Element,
    node: MappedSemanticNode | dict[str, Any],
    ref_index: int,
    parent_sec_id: str | None = None,
    template_graphics: dict[str, str] | None = None,
    template_formula_ids: dict[str, str] | None = None,
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
) -> None:
    ref_index = 1
    for node in nodes:
        ref_index = _append_mapped_node(
            parent,
            node,
            ref_index,
            parent_sec_id=parent_sec_id,
            template_graphics=template_graphics,
            template_formula_ids=template_formula_ids,
        )


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
        keywords_text = _text_of(keywords_data, "keywords")
        for token in re.split(r"[,;]\s*", keywords_text):
            token = token.strip()
            if not token:
                continue
            kwd = etree.SubElement(kwd_group, "kwd")
            set_lxml_text(
                kwd,
                token,
                log_context={"semantic_type": "keywords", "source": "-", "field": "kwd"},
            )


def _normalize_person_name_elements(article: etree._Element) -> None:
    """Strip surrounding whitespace from author name fields preserved from the template."""
    for element in article.iter():
        if element.tag not in _PERSON_NAME_TAGS:
            continue
        if element.text is None:
            continue
        set_lxml_text(
            element,
            normalize_person_name_text(element.text),
            log_context={"semantic_type": "author", "source": "-", "field": element.tag},
        )


def _apply_back_matter(article: etree._Element, back: dict[str, Any]) -> None:
    references = back.get("references") or []
    back_el = article.find("back")
    if back_el is None:
        if not references:
            return
        back_el = etree.SubElement(article, "back")
    if not references:
        return

    ref_list = back_el.find("ref-list")
    if ref_list is None:
        ref_list = etree.SubElement(back_el, "ref-list")
    if ref_list.find("title") is None:
        title = etree.SubElement(ref_list, "title")
        set_lxml_text(
            title,
            "References",
            log_context={"semantic_type": "reference_list", "source": "-", "field": "title"},
        )
    for child in list(ref_list):
        if child.tag == "ref":
            ref_list.remove(child)
    ref_index = 1
    for reference in references:
        _append_reference(ref_list, reference, ref_index)
        ref_index += 1


def generate_jats_xml(
    template_path: str | Path,
    mapping: SemanticMappingBody | dict[str, Any],
) -> str:
    """Generate IEEE JATS XML using a client template skeleton and semantic mapping."""
    path = Path(template_path)
    if not path.exists():
        raise XmlGenerationError(f"Template XML not found: {path}")

    if isinstance(mapping, SemanticMappingBody):
        body = mapping
    else:
        body = SemanticMappingBody.model_validate(mapping.get("mapping", mapping))

    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        raise XmlGenerationError(f"Invalid template XML: {exc}") from exc

    article = tree.getroot()
    if article.tag != "article":
        raise XmlGenerationError("Template root element must be <article>")

    _apply_front_matter(article, body.front)

    template_graphics = _extract_template_figure_graphics(article)
    template_formula_ids = _extract_template_display_formula_ids(article)

    body_el = article.find("body")
    if body_el is not None:
        for child in list(body_el):
            body_el.remove(child)
        _append_mapped_nodes(
            body_el,
            list(body.body),
            template_graphics=template_graphics,
            template_formula_ids=template_formula_ids,
        )

    _apply_back_matter(article, body.back)
    _normalize_person_name_elements(article)

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
) -> str:
    """Convenience: Stage 1 IR → mapping → JATS XML without LLM."""
    from app.services.ir_semantic_adapter import ir_to_semantic_mapping

    mapping = ir_to_semantic_mapping(ir)
    return generate_jats_xml(template_path, mapping)
