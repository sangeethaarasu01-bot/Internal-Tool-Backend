"""Convert Stage 1 semantic IR into SemanticMappingBody (deterministic, no LLM).

Used as a fallback when LLM mapping is unavailable and as the baseline mapping
before optional LLM refinement.
"""

from __future__ import annotations

from typing import Any

from app.models.semantic_mapping import MappedInlineElement, MappedSemanticNode, SemanticMappingBody

_IR_TYPE_TO_SEMANTIC = {
    "title": "metadata",
    "heading": "heading",
    "paragraph": "paragraph",
    "display_math": "display_math",
    "inline_math": "inline_math",
    "figure": "figure",
    "figure_caption": "caption",
    "table": "table",
    "table_caption": "caption",
    "reference": "reference",
    "abstract": "abstract",
    "keywords": "keywords",
    "author": "author",
    "affiliation": "affiliation",
    "list": "list",
    "list_item": "list_item",
    "unknown": "unknown",
}


def _node_text(node: dict[str, Any]) -> str | None:
    if node.get("text"):
        return str(node["text"])
    parts: list[str] = []
    for item in node.get("elements") or []:
        if item.get("value"):
            parts.append(str(item["value"]))
        elif item.get("latex"):
            parts.append(str(item["latex"]))
    return "".join(parts) if parts else None


def _inline_elements(node: dict[str, Any]) -> list[MappedInlineElement]:
    elements: list[MappedInlineElement] = []
    for item in node.get("elements") or []:
        item_type = item.get("type", "text")
        if item_type == "inline_math":
            elements.append(MappedInlineElement(type="inline_math", latex=item.get("latex")))
        else:
            elements.append(MappedInlineElement(type="text", value=item.get("value")))
    return elements


def _ir_node_to_mapped(node: dict[str, Any] | None) -> MappedSemanticNode | None:
    if not node:
        return None
    ir_type = (node.get("type") or "paragraph").lower()
    semantic_type = _IR_TYPE_TO_SEMANTIC.get(ir_type, "paragraph")
    children = [_ir_node_to_mapped(child) for child in node.get("children") or []]
    children = [child for child in children if child is not None]
    return MappedSemanticNode(
        semantic_type=semantic_type,
        source_block_ids=list(node.get("source_block_ids") or []),
        source_node_ids=[ir_type],
        text=_node_text(node),
        latex=node.get("latex"),
        label=node.get("label"),
        elements=_inline_elements(node),
        rows=node.get("rows"),
        children=children,
        confidence=node.get("confidence"),
    )


def _section_to_mapped(section: dict[str, Any]) -> MappedSemanticNode:
    heading_el = section.get("heading_element") or {}
    content_nodes = [
        mapped
        for item in (section.get("content") or []) + (section.get("paragraphs") or [])
        if (mapped := _ir_node_to_mapped(item)) is not None
    ]
    for subsection in section.get("subsections") or []:
        content_nodes.append(_section_to_mapped(subsection))

    level = section.get("level") or 1
    semantic_type = "subsection" if level > 1 else "heading"
    return MappedSemanticNode(
        semantic_type=semantic_type,
        text=section.get("heading") or heading_el.get("text"),
        label=heading_el.get("label"),
        source_block_ids=list(heading_el.get("source_block_ids") or section.get("content_source_block_ids") or []),
        elements=_inline_elements(heading_el),
        children=content_nodes,
        metadata={"level": level},
    )


def ir_to_semantic_mapping(ir: dict[str, Any]) -> SemanticMappingBody:
    """Build a :class:`SemanticMappingBody` from partitioned Stage 1 IR."""
    front_raw = ir.get("front") or {}
    front: dict[str, Any] = {}

    title = _ir_node_to_mapped(front_raw.get("title"))
    if title:
        front["title"] = title.model_dump(mode="json")

    abstract = _ir_node_to_mapped(front_raw.get("abstract"))
    if abstract:
        front["abstract"] = abstract.model_dump(mode="json")

    keywords = _ir_node_to_mapped(front_raw.get("keywords"))
    if keywords:
        front["keywords"] = keywords.model_dump(mode="json")

    authors = [
        mapped.model_dump(mode="json")
        for author in front_raw.get("authors") or []
        if (mapped := _ir_node_to_mapped(author)) is not None
    ]
    if authors:
        front["authors"] = authors

    affiliations = [
        mapped.model_dump(mode="json")
        for aff in front_raw.get("affiliations") or []
        if (mapped := _ir_node_to_mapped(aff)) is not None
    ]
    if affiliations:
        front["affiliations"] = affiliations

    body: list[MappedSemanticNode] = []
    body_raw = ir.get("body") or {}
    for section in body_raw.get("sections") or []:
        body.append(_section_to_mapped(section))
    for loose in body_raw.get("loose_paragraphs") or []:
        if mapped := _ir_node_to_mapped(loose):
            body.append(mapped)

    back_raw = ir.get("back") or {}
    back: dict[str, Any] = {}
    references = [
        mapped.model_dump(mode="json")
        for ref in back_raw.get("references") or []
        if (mapped := _ir_node_to_mapped(ref)) is not None
    ]
    if references:
        back["references"] = references

    return SemanticMappingBody(front=front, body=body, back=back)
