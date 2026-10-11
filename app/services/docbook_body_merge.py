"""Merge partitioned semantic IR (PDF) into DocBook 5.0 book narrative content."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.ir_semantic_adapter import ensure_semantic_mapping_body
from app.services.template_format import DOCBOOK_NS
from app.utils.book_running_headers import is_book_running_header_text
from app.utils.xml_helpers import iter_element_children, xml_local_name
from app.utils.xml_text import set_lxml_text

logger = logging.getLogger(__name__)

_BODY_LOCAL_NAMES = frozenset(
    {
        "part",
        "chapter",
        "appendix",
        "preface",
        "introduction",
        "colophon",
        "dedication",
        "acknowledgements",
        "bibliography",
    }
)


@dataclass
class DocBookBodyMergeResult:
    applied: bool = False
    removed_template_elements: int = 0
    warnings: list[str] = field(default_factory=list)


def _ns(tag: str) -> str:
    return f"{{{DOCBOOK_NS}}}{tag}"


def _node_text(node: MappedSemanticNode) -> str:
    if node.text and str(node.text).strip():
        return str(node.text).strip()
    parts: list[str] = []
    for element in node.elements or []:
        if element.value:
            parts.append(str(element.value))
        elif element.latex:
            parts.append(str(element.latex))
    return "".join(parts).strip()


def _heading_level(node: MappedSemanticNode) -> int:
    meta = node.metadata or {}
    level = meta.get("level")
    if isinstance(level, int) and level > 0:
        return level
    if node.semantic_type == "subsection":
        return 2
    return 1


def _strip_book_narrative(root: etree._Element) -> int:
    removed = 0
    for child in list(iter_element_children(root)):
        name = xml_local_name(child)
        if name == "info":
            continue
        if name in _BODY_LOCAL_NAMES or name == "part":
            root.remove(child)
            removed += 1
    return removed


def _append_paragraph(parent: etree._Element, node: MappedSemanticNode) -> None:
    text = _node_text(node)
    if not text:
        return
    if is_book_running_header_text(text):
        return
    para = etree.SubElement(parent, _ns("para"))
    set_lxml_text(para, text)


def _append_display_math(parent: etree._Element, node: MappedSemanticNode) -> None:
    latex = (node.latex or _node_text(node)).strip()
    if not latex:
        return
    equation = etree.SubElement(parent, _ns("equation"))
    mathphrase = etree.SubElement(equation, _ns("mathphrase"))
    set_lxml_text(mathphrase, latex)


def _append_mapped_nodes(parent: etree._Element, nodes: list[MappedSemanticNode]) -> etree._Element:
    """Append IR nodes under ``parent``; return the deepest open container."""
    container = parent
    for node in nodes:
        container = _append_single_node(container, node)
    return container


def _append_single_node(
    parent: etree._Element,
    node: MappedSemanticNode,
) -> etree._Element:
    st = node.semantic_type
    if st in {"heading", "subsection"}:
        level = _heading_level(node)
        if level <= 1 or xml_local_name(parent) == "book":
            chapter = etree.SubElement(parent, _ns("chapter"))
            if node.text and str(node.text).strip():
                title = etree.SubElement(chapter, _ns("title"))
                set_lxml_text(title, str(node.text).strip())
            if node.children:
                return _append_mapped_nodes(chapter, list(node.children))
            return chapter
        section = etree.SubElement(parent, _ns("section"))
        if node.text and str(node.text).strip():
            title = etree.SubElement(section, _ns("title"))
            set_lxml_text(title, str(node.text).strip())
        if node.children:
            return _append_mapped_nodes(section, list(node.children))
        return section

    if st == "paragraph":
        _append_paragraph(parent, node)
        return parent
    if st == "display_math":
        _append_display_math(parent, node)
        return parent
    if st == "figure":
        text = _node_text(node)
        if text:
            figure = etree.SubElement(parent, _ns("figure"))
            title = etree.SubElement(figure, _ns("title"))
            set_lxml_text(title, text)
        return parent
    if st == "table" and node.rows:
        table = etree.SubElement(parent, _ns("table"))
        tgroup = etree.SubElement(table, _ns("tgroup"), attrib={"cols": str(len(node.rows[0]))})
        tbody = etree.SubElement(tgroup, _ns("tbody"))
        for row in node.rows:
            row_el = etree.SubElement(tbody, _ns("row"))
            for cell in row:
                entry = etree.SubElement(row_el, _ns("entry"))
                set_lxml_text(entry, str(cell))
        return parent
    if st in {"list", "unknown"} and node.children:
        return _append_mapped_nodes(parent, list(node.children))
    if node.children:
        return _append_mapped_nodes(parent, list(node.children))
    if st == "paragraph" or _node_text(node):
        _append_paragraph(parent, node)
    return parent


def _append_references(book: etree._Element, mapping: SemanticMappingBody) -> None:
    refs = mapping.back.get("references") if mapping.back else None
    if not refs:
        return
    chapter = etree.SubElement(book, _ns("chapter"))
    chapter.set("role", "bibliography")
    title = etree.SubElement(chapter, _ns("title"))
    set_lxml_text(title, "References")
    bibliolist = etree.SubElement(chapter, _ns("bibliolist"))
    for ref in refs:
        if isinstance(ref, dict):
            ref = MappedSemanticNode.model_validate(ref)
        text = _node_text(ref)
        if not text:
            continue
        bibliomixed = etree.SubElement(bibliolist, _ns("bibliomixed"))
        set_lxml_text(bibliomixed, text)


def apply_pdf_body_to_docbook_book(
    root: etree._Element,
    mapping: SemanticMappingBody | dict[str, Any] | None,
    *,
    ir: dict[str, Any] | None = None,
) -> DocBookBodyMergeResult:
    """
    Replace template chapter/part narrative with PDF body from semantic mapping.

    Book-level ``<info>`` is left unchanged (metadata overlay runs separately).
    When mapping has no body nodes, the template narrative is preserved.
    """
    result = DocBookBodyMergeResult()
    body: SemanticMappingBody
    try:
        if mapping is None and ir is not None:
            from app.services.ir_semantic_adapter import ir_to_semantic_mapping

            body = ir_to_semantic_mapping(ir)
        elif mapping is not None:
            body = ensure_semantic_mapping_body(mapping)
        else:
            result.warnings.append("DocBook body merge skipped: no mapping or IR.")
            return result
    except ValueError as exc:
        result.warnings.append(f"DocBook body merge skipped: {exc}")
        return result

    nodes = list(body.body or [])
    if not nodes:
        result.warnings.append(
            "DocBook body merge skipped: PDF IR has no body sections yet."
        )
        return result

    removed = _strip_book_narrative(root)
    result.removed_template_elements = removed
    _append_mapped_nodes(root, nodes)
    _append_references(root, body)
    result.applied = True
    logger.info(
        "docbook_body_merge applied removed=%s body_nodes=%s",
        removed,
        len(nodes),
    )
    return result
