"""Compact IR and template schema payloads before LLM calls."""

from __future__ import annotations

from typing import Any

_MAX_TEXT_LEN = 1200
_MAX_REFERENCES = 25

_IR_NODE_KEYS = (
    "type",
    "text",
    "latex",
    "label",
    "heading",
    "level",
    "elements",
    "children",
    "rows",
    "keywords",
    "source_block_ids",
    "list_type",
    "list_marker",
)
_SECTION_KEYS = ("heading", "level", "heading_element", "content", "subsections", "paragraphs")


def _truncate(value: str | None, limit: int = _MAX_TEXT_LEN) -> str | None:
    if not value:
        return value
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _compact_node(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not node:
        return None
    compact = {key: node[key] for key in _IR_NODE_KEYS if key in node and node[key] not in (None, [], "")}
    if not compact.get("text"):
        parts: list[str] = []
        for item in node.get("elements") or []:
            if item.get("value"):
                parts.append(str(item["value"]))
            elif item.get("latex"):
                parts.append(str(item["latex"]))
        if parts:
            compact["text"] = _truncate("".join(parts))
    if compact.get("text"):
        compact["text"] = _truncate(str(compact["text"]))
    if compact.get("latex"):
        compact["latex"] = _truncate(str(compact["latex"]))
    if compact.get("elements"):
        compact["elements"] = [
            {k: v for k, v in element.items() if k in {"type", "value", "latex"} and v}
            for element in compact["elements"]
        ]
    if compact.get("children"):
        compact["children"] = [
            child for child in (_compact_node(child) for child in compact["children"]) if child
        ]
    return compact or None


def _compact_section(section: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in _SECTION_KEYS:
        if key not in section:
            continue
        value = section[key]
        if key == "heading_element":
            compact[key] = _compact_node(value)
        elif key == "subsections":
            compact[key] = [_compact_section(sub) for sub in value]
        elif key in {"content", "paragraphs"}:
            compact[key] = [node for node in (_compact_node(item) for item in value) if node]
        else:
            compact[key] = value
    return compact


def compact_ir_for_llm(ir: dict[str, Any]) -> dict[str, Any]:
    """Strip layout metadata and keep semantic content for LLM mapping."""
    front = ir.get("front") or {}
    compact_front: dict[str, Any] = {}
    for key, value in front.items():
        if key in {"authors", "affiliations", "other"} and isinstance(value, list):
            compact_front[key] = [node for node in (_compact_node(item) for item in value) if node]
        elif isinstance(value, dict):
            compact_front[key] = _compact_node(value)
        else:
            compact_front[key] = value

    body = ir.get("body") or {}
    compact_body = {
        "sections": [_compact_section(section) for section in body.get("sections") or []],
        "loose_paragraphs": [
            node for node in (_compact_node(item) for item in body.get("loose_paragraphs") or []) if node
        ],
    }

    back = ir.get("back") or {}
    compact_back: dict[str, Any] = {}
    if back.get("reference_list"):
        compact_back["reference_list"] = _compact_node(back["reference_list"])
    compact_back["references"] = [
        node
        for node in (
            _compact_node(item) for item in (back.get("references") or [])[:_MAX_REFERENCES]
        )
        if node
    ]
    if back.get("other"):
        compact_back["other"] = [
            node for node in (_compact_node(item) for item in back.get("other") or []) if node
        ]

    return {"front": compact_front, "body": compact_body, "back": compact_back}


def compact_template_schema_for_llm(schema: dict[str, Any]) -> dict[str, Any]:
    """Send only template structure hints to the LLM, not the full tag dictionary."""
    return {
        "template_name": schema.get("template_name"),
        "root_tag": schema.get("root_tag"),
        "section_boundaries": schema.get("section_boundaries"),
        "scope_markers": schema.get("scope_markers"),
        "required_paths": (schema.get("required_paths") or [])[:80],
        "tag_names": list((schema.get("tags") or {}).keys())[:120],
        "llm_hints": schema.get("llm_hints"),
    }
