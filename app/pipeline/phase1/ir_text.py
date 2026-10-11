"""Plain text from IR nodes (no LLM)."""

from __future__ import annotations

from app.models.ir_schema import IRNode


def ir_node_plain_text(node: IRNode | None) -> str:
    if node is None:
        return ""
    parts: list[str] = []
    for element in node.elements or []:
        if element.type == "text":
            parts.append(element.value or "")
        elif element.type == "inline_math":
            parts.append(element.latex or "")
    if parts:
        return "".join(parts).strip()
    if node.children:
        child_parts = [ir_node_plain_text(child) for child in node.children]
        child_parts = [part for part in child_parts if part]
        if child_parts:
            return " ".join(child_parts).strip()
    return (node.latex or node.text or "").strip()
