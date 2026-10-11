"""Normalize and deduplicate author names from Stage 1 IR / semantic mapping."""

from __future__ import annotations

import re

from app.models.semantic_mapping import MappedSemanticNode
from app.services.layout.semantic_patterns import parse_author_names
from app.utils.proof_pdf import is_plausible_author_name

_TRAILING_AFFILIATION_MARK_RE = re.compile(r"\s+\d+\s*$")
_INCOMPLETE_PAREN_RE = re.compile(r"\s*\([^)]*$")
_AND_PREFIX_RE = re.compile(r"^and\s+", re.I)


def clean_author_display_name(name: str) -> str:
    """Strip affiliation superscripts and broken corresponding-author email fragments."""
    text = (name or "").strip()
    text = _AND_PREFIX_RE.sub("", text)
    text = _INCOMPLETE_PAREN_RE.sub("", text)
    text = re.sub(r"\([^)]*\)", "", text).strip()
    text = _TRAILING_AFFILIATION_MARK_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")
    return text


def author_dedup_key(name: str) -> str:
    """Case-insensitive key for matching the same person across IR variants."""
    clean = clean_author_display_name(name)
    letters = re.sub(r"[^A-Za-z\s]", "", clean)
    return " ".join(letters.lower().split())


def _author_display_score(name: str) -> int:
    score = 0
    if _INCOMPLETE_PAREN_RE.search(name):
        score -= 20
    if _TRAILING_AFFILIATION_MARK_RE.search(name):
        score -= 8
    if name.isupper():
        score -= 3
    if name != name.upper() and name != name.lower():
        score += 4
    if "@" in name:
        score -= 15
    return score


def deduplicate_author_names(names: list[str]) -> list[str]:
    """Return unique author display names, preserving first-seen order."""
    best: dict[str, str] = {}
    order: list[str] = []
    for raw in names:
        for candidate in parse_author_names(raw) or ([raw] if raw else []):
            clean = clean_author_display_name(candidate)
            key = author_dedup_key(clean)
            if len(key) < 4 or not is_plausible_author_name(clean):
                continue
            existing = best.get(key)
            if existing is None or _author_display_score(clean) > _author_display_score(existing):
                best[key] = clean
            if key not in order:
                order.append(key)
    return [best[key] for key in order if key in best]


def _author_text(node: MappedSemanticNode) -> str:
    if node.text:
        return node.text.strip()
    for element in node.elements:
        if element.value:
            return str(element.value).strip()
    return ""


def deduplicate_mapped_authors(nodes: list[MappedSemanticNode]) -> list[MappedSemanticNode]:
    """Collapse duplicate author nodes (e.g. byline + corresponding-author line)."""
    if not nodes:
        return []

    prototype: dict[str, MappedSemanticNode] = {}
    raw_names: list[str] = []
    for node in nodes:
        text = _author_text(node)
        if text:
            raw_names.append(text)
        for candidate in parse_author_names(text) or ([text] if text else []):
            key = author_dedup_key(clean_author_display_name(candidate))
            if len(key) >= 4 and key not in prototype:
                prototype[key] = node

    deduped_names = deduplicate_author_names(raw_names)
    result: list[MappedSemanticNode] = []
    for display in deduped_names:
        key = author_dedup_key(display)
        base = prototype.get(key, nodes[0])
        result.append(
            MappedSemanticNode(
                semantic_type="author",
                source_block_ids=list(base.source_block_ids),
                source_node_ids=list(base.source_node_ids),
                text=display,
                elements=[],
                children=[],
                confidence=base.confidence,
            )
        )
    return result
