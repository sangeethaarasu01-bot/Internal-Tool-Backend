"""Remove overlapping / duplicate book paragraphs (PDF merge artifacts)."""

from __future__ import annotations

import re
from typing import Any

_MIN_SUBSTRING_DEDUP_CHARS = 160


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()


def _compact_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _is_subsumed_paragraph_text(shorter: str, longer: str) -> bool:
    if not shorter or not longer or len(shorter) >= len(longer):
        return False
    if shorter in longer:
        return True
    compact_short = _compact_alnum(shorter)
    compact_long = _compact_alnum(longer)
    if (
        len(compact_short) >= _MIN_SUBSTRING_DEDUP_CHARS
        and compact_short in compact_long
        and len(compact_short) >= int(len(compact_long) * 0.55)
    ):
        return True
    if len(shorter) < _MIN_SUBSTRING_DEDUP_CHARS:
        return False
    probe = shorter[: min(len(shorter), 2400)]
    if len(probe) > 200:
        trimmed = probe.rsplit(" ", 1)[0]
        if len(trimmed) > 200 and trimmed in longer:
            return True
    prefix_len = int(len(shorter) * 0.88)
    if prefix_len > 200 and longer.startswith(shorter[:prefix_len]):
        return True
    return False


def _paragraph_text_from_ir_node(node: dict[str, Any]) -> str:
    if node.get("text"):
        return _normalize_text(str(node["text"]))
    parts: list[str] = []
    for item in node.get("elements") or []:
        if isinstance(item, dict) and item.get("value"):
            parts.append(str(item["value"]))
    if parts:
        return _normalize_text("".join(parts))
    return ""


def dedupe_ir_paragraph_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Drop paragraph IR nodes whose text is duplicated or strictly contained in another.

    Keeps the longest paragraph when one body of text subsumes another (common when
    page-span segments and full merged paragraphs are both emitted).
    """
    if len(nodes) < 2:
        return nodes

    indexed: list[tuple[int, dict[str, Any], str]] = []
    for index, node in enumerate(nodes):
        if (node.get("type") or "paragraph").lower() != "paragraph":
            continue
        text = _paragraph_text_from_ir_node(node)
        if text:
            indexed.append((index, node, text))

    if len(indexed) < 2:
        return nodes

    remove_indices: set[int] = set()
    for i, (_ii, _ni, ti) in enumerate(indexed):
        if _ii in remove_indices:
            continue
        for j, (_ij, _nj, tj) in enumerate(indexed):
            if i == j or _ij in remove_indices:
                continue
            if ti == tj:
                if _ij > _ii:
                    remove_indices.add(_ij)
                continue
            if _is_subsumed_paragraph_text(ti, tj):
                remove_indices.add(_ii)
                break
            if _is_subsumed_paragraph_text(tj, ti):
                remove_indices.add(_ij)

    if not remove_indices:
        return nodes
    return [node for index, node in enumerate(nodes) if index not in remove_indices]


def dedupe_ir_section(section: dict[str, Any]) -> dict[str, Any]:
    """Dedupe ``content`` / ``paragraphs`` on a body section (recursive)."""
    out = dict(section)
    content = list(out.get("content") or [])
    paragraphs = list(out.get("paragraphs") or [])
    if content and paragraphs:
        # Legacy IR stored the same nodes in both fields — prefer ``content`` only.
        paragraphs = []
    elif not content and paragraphs:
        content = paragraphs
        paragraphs = []

    content = dedupe_ir_paragraph_nodes(content)
    out["content"] = content
    if paragraphs:
        out["paragraphs"] = dedupe_ir_paragraph_nodes(paragraphs)
    else:
        out.pop("paragraphs", None)

    subs = []
    for sub in out.get("subsections") or []:
        if isinstance(sub, dict):
            subs.append(dedupe_ir_section(sub))
        else:
            subs.append(sub)
    out["subsections"] = subs
    return out


def dedupe_ir_body(body: dict[str, Any]) -> dict[str, Any]:
    sections = [
        dedupe_ir_section(section) if isinstance(section, dict) else section
        for section in body.get("sections") or []
    ]
    loose = dedupe_ir_paragraph_nodes(list(body.get("loose_paragraphs") or []))
    return {**body, "sections": sections, "loose_paragraphs": loose}
