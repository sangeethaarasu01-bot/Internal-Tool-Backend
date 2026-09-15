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
from app.utils.xml_text import sanitize_xml_text, set_lxml_text

MML_NS = "http://www.w3.org/1998/Math/MathML"
XLINK_NS = "http://www.w3.org/1999/xlink"
NSMAP = {
    "mml": MML_NS,
    "xlink": XLINK_NS,
}

_SECTION_SEMANTIC_TYPES = frozenset({"section", "heading", "subsection"})


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
    if isinstance(node, MappedSemanticNode):
        if node.text:
            return sanitize_xml_text(node.text, log_context=ctx)
        if node.latex:
            return sanitize_xml_text(node.latex, log_context={**ctx, "field": "latex"})
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
        return "".join(parts)
    if node.get("text"):
        return sanitize_xml_text(str(node["text"]), log_context=ctx)
    if node.get("latex"):
        return sanitize_xml_text(str(node["latex"]), log_context={**ctx, "field": "latex"})
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
    return "".join(parts)


def _as_mapped(node: MappedSemanticNode | dict[str, Any]) -> MappedSemanticNode:
    if isinstance(node, MappedSemanticNode):
        return node
    return MappedSemanticNode.model_validate(node)


def _append_inline_content(parent: etree._Element, node: MappedSemanticNode | dict[str, Any]) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "inline")
    if mapped.elements:
        for element in mapped.elements:
            if element.type == "inline_math" and element.latex:
                inline = etree.SubElement(parent, "inline-formula")
                tex = etree.SubElement(inline, "tex-math", notation="LaTeX")
                set_lxml_text(
                    tex,
                    element.latex,
                    log_context={**ctx, "field": "inline_math.latex"},
                )
            elif element.value:
                cleaned = sanitize_xml_text(
                    element.value,
                    log_context={**ctx, "field": "inline.value"},
                )
                parent.text = (parent.text or "") + cleaned
        return
    set_lxml_text(parent, _text_of(mapped), log_context=ctx)


def _append_paragraph(parent: etree._Element, node: MappedSemanticNode | dict[str, Any]) -> None:
    paragraph = etree.SubElement(parent, "p")
    _append_inline_content(paragraph, node)


def _append_display_math(parent: etree._Element, node: MappedSemanticNode | dict[str, Any]) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "display_math")
    formula = etree.SubElement(parent, "disp-formula")
    if mapped.label:
        label = etree.SubElement(formula, "label")
        set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
    tex = etree.SubElement(formula, "tex-math", notation="LaTeX")
    set_lxml_text(tex, mapped.latex or _text_of(mapped, "latex"), log_context={**ctx, "field": "latex"})


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


def _append_figure(parent: etree._Element, node: MappedSemanticNode | dict[str, Any]) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "figure")
    figure = etree.SubElement(parent, "fig")
    if mapped.label:
        label = etree.SubElement(figure, "label")
        set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
    for child in mapped.children:
        if child.semantic_type == "caption":
            caption = etree.SubElement(figure, "caption")
            caption_p = etree.SubElement(caption, "p")
            set_lxml_text(caption_p, _text_of(child, "caption"), log_context=_log_context_for(child, "caption"))
    if not any(child.semantic_type == "caption" for child in mapped.children):
        caption_text = _text_of(mapped, "caption")
        if caption_text:
            caption = etree.SubElement(figure, "caption")
            caption_p = etree.SubElement(caption, "p")
            set_lxml_text(caption_p, caption_text, log_context={**ctx, "field": "caption"})


def _append_reference(parent: etree._Element, node: MappedSemanticNode | dict[str, Any], index: int) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "reference")
    ref = etree.SubElement(parent, "ref", id=f"ref{index}")
    label_text = mapped.label or f"[{index}]"
    label = etree.SubElement(ref, "label")
    set_lxml_text(label, label_text, log_context={**ctx, "field": "label"})
    citation = etree.SubElement(ref, "mixed-citation")
    set_lxml_text(citation, _text_of(mapped, "citation"), log_context={**ctx, "field": "citation"})


def _append_section(parent: etree._Element, node: MappedSemanticNode | dict[str, Any], sec_index: int) -> None:
    mapped = _as_mapped(node)
    ctx = _log_context_for(mapped, "section")
    sec = etree.SubElement(parent, "sec", id=f"sec{sec_index}")
    if mapped.label:
        label = etree.SubElement(sec, "label")
        set_lxml_text(label, mapped.label, log_context={**ctx, "field": "label"})
    title_text = mapped.text or ""
    if title_text:
        title = etree.SubElement(sec, "title")
        set_lxml_text(title, title_text, log_context={**ctx, "field": "title"})
    _append_mapped_nodes(sec, list(mapped.children))


def _append_mapped_node(parent: etree._Element, node: MappedSemanticNode | dict[str, Any], ref_index: int) -> int:
    mapped = _as_mapped(node)
    semantic_type = mapped.semantic_type

    if semantic_type in _SECTION_SEMANTIC_TYPES:
        _append_section(parent, mapped, len(parent.findall("sec")) + 1)
        return ref_index
    if semantic_type == "paragraph":
        _append_paragraph(parent, mapped)
        return ref_index
    if semantic_type == "display_math":
        _append_display_math(parent, mapped)
        return ref_index
    if semantic_type == "table":
        _append_table(parent, mapped)
        return ref_index
    if semantic_type == "figure":
        _append_figure(parent, mapped)
        return ref_index
    if semantic_type == "reference":
        _append_reference(parent, mapped, ref_index)
        return ref_index + 1
    if semantic_type == "list":
        list_type = "order"
        if mapped.metadata and mapped.metadata.get("list_type"):
            list_type = str(mapped.metadata["list_type"])
        list_el = etree.SubElement(parent, "list", list_type=list_type)
        for child in mapped.children:
            item = etree.SubElement(list_el, "list-item")
            item_p = etree.SubElement(item, "p")
            set_lxml_text(item_p, _text_of(child), log_context=_log_context_for(child, "list_item"))
        return ref_index

    text = _text_of(mapped)
    if text:
        _append_paragraph(parent, mapped)
    return ref_index


def _append_mapped_nodes(parent: etree._Element, nodes: list[MappedSemanticNode | dict[str, Any]]) -> None:
    ref_index = 1
    for node in nodes:
        ref_index = _append_mapped_node(parent, node, ref_index)


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
        _append_paragraph(abstract, abstract_data)

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


def _apply_back_matter(article: etree._Element, back: dict[str, Any]) -> None:
    back_el = article.find("back")
    if back_el is None:
        return
    ref_list = back_el.find("ref-list")
    references = back.get("references") or []
    if ref_list is None and references:
        ref_list = etree.SubElement(back_el, "ref-list")
        title = etree.SubElement(ref_list, "title")
        set_lxml_text(
            title,
            "References",
            log_context={"semantic_type": "reference_list", "source": "-", "field": "title"},
        )
    if ref_list is None:
        return
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

    body_el = article.find("body")
    if body_el is not None:
        for child in list(body_el):
            body_el.remove(child)
        _append_mapped_nodes(body_el, list(body.body))

    _apply_back_matter(article, body.back)

    xml_bytes = etree.tostring(
        article,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=tree.docinfo.doctype if tree.docinfo.doctype else None,
    )
    return xml_bytes.decode("utf-8")


def generate_jats_xml_from_ir(
    template_path: str | Path,
    ir: dict[str, Any],
) -> str:
    """Convenience: Stage 1 IR → mapping → JATS XML without LLM."""
    from app.services.ir_semantic_adapter import ir_to_semantic_mapping

    mapping = ir_to_semantic_mapping(ir)
    return generate_jats_xml(template_path, mapping)
