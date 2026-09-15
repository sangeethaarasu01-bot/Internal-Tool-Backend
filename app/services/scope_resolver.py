"""Filter IR JSON and template schema by user scope (front / body / back / full).

Deterministic only — no LLM calls.  Sits between Stage 1 extraction and the
LLM semantic mapper: both ``template_schema`` and ``SemanticDocument`` IR are
trimmed to the sections the user requested before mapping to JATS fields.

The live IR shape comes from :meth:`SemanticDocument.to_ir_json`::

    {
        "pipeline_version": "2.0.0",
        "front": { "title": {...}, "abstract": {...}, ... },
        "body":  { "sections": [...], "loose_paragraphs": [...] },
        "back":  { "references": [...], ... },
        "unknown": [...],
        "completeness": {...}
    }

A legacy flat ``elements[]`` list with per-element ``section`` tags is also
supported for forward-compatible tests and API payloads.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from app.models.template_schema import TemplateSchema

logger = logging.getLogger(__name__)

SECTION_ROOTS = ("front", "body", "back")
CANONICAL_SCOPES = frozenset({"front", "body", "back", "full"})

_SCOPE_ALIASES: dict[str, str] = {
    "front": "front",
    "frontmatter": "front",
    "front matter": "front",
    "front meta": "front",
    "front metadata": "front",
    "front section": "front",
    "front only": "front",
    "metadata front": "front",
    "back": "back",
    "backmatter": "back",
    "back matter": "back",
    "back meta": "back",
    "back metadata": "back",
    "back section": "back",
    "back only": "back",
    "references": "back",
    "references only": "back",
    "bibliography": "back",
    "body": "body",
    "bodymatter": "body",
    "body matter": "body",
    "body section": "body",
    "body only": "body",
    "full": "full",
    "complete": "full",
    "all": "full",
    "entire": "full",
    "whole": "full",
    "full document": "full",
    "full article": "full",
}


class InvalidScopeError(ValueError):
    """Raised when a scope instruction cannot be normalized."""


def normalize_scope(raw_scope: str) -> str:
    """Map user phrasing to canonical ``front`` | ``body`` | ``back`` | ``full``.

    Raises :class:`InvalidScopeError` for unrecognized input.
    """
    if not raw_scope or not str(raw_scope).strip():
        raise InvalidScopeError("Scope instruction is empty")

    normalized = _normalize_scope_text(str(raw_scope))
    if normalized in _SCOPE_ALIASES:
        return _SCOPE_ALIASES[normalized]

    tokens = normalized.split()
    if (
        "full" in tokens
        or "complete" in tokens
        or "all" in tokens
        or normalized in {"entire", "whole", "entire document", "full document", "full article"}
    ):
        return "full"
    if "frontmatter" in normalized or "front matter" in normalized or "front meta" in normalized:
        return "front"
    if "backmatter" in normalized or "back matter" in normalized or "back meta" in normalized:
        return "back"
    if "bodymatter" in normalized or "body matter" in normalized:
        return "body"
    if "front" in tokens and "back" not in tokens and "body" not in tokens:
        return "front"
    if "back" in tokens and "front" not in tokens and "body" not in tokens:
        return "back"
    if "body" in tokens and "front" not in tokens and "back" not in tokens:
        return "body"
    if normalized.startswith("front"):
        return "front"
    if normalized.startswith("back"):
        return "back"
    if normalized.startswith("body"):
        return "body"

    raise InvalidScopeError(f"Unrecognized scope instruction: {raw_scope!r}")


def resolve_allowed_sections(scope: str) -> list[str]:
    """Return top-level section names for a canonical scope."""
    canonical = normalize_scope(scope) if scope not in CANONICAL_SCOPES else scope
    if canonical not in CANONICAL_SCOPES:
        raise InvalidScopeError(f"Invalid canonical scope: {scope!r}")
    if canonical == "front":
        return ["front"]
    if canonical == "body":
        return ["body"]
    if canonical == "back":
        return ["back"]
    return list(SECTION_ROOTS)


def filter_template_schema(
    template_schema: dict[str, Any] | TemplateSchema,
    allowed_sections: list[str],
) -> dict[str, Any]:
    """Return a template-schema subtree for ``allowed_sections`` only."""
    if isinstance(template_schema, TemplateSchema):
        schema_dict = template_schema.model_dump(mode="json")
    else:
        schema_dict = copy.deepcopy(template_schema)

    allowed = set(allowed_sections)
    filtered = copy.deepcopy(schema_dict)

    section_boundaries = schema_dict.get("section_boundaries", {})
    filtered["section_boundaries"] = {
        section: copy.deepcopy(section_boundaries[section])
        for section in allowed
        if section in section_boundaries
    }

    filtered["required_paths"] = [
        path
        for path in schema_dict.get("required_paths", [])
        if _path_belongs_to_sections(path, allowed)
    ]

    scope_markers = schema_dict.get("scope_markers", {})
    filtered["scope_markers"] = {
        key: value
        for key, value in scope_markers.items()
        if key in allowed or key == "full"
    }

    filtered["tags"] = _filter_tags(schema_dict.get("tags", {}), allowed, filtered["section_boundaries"])

    # llm_hints are global safety rails — keep unchanged for all scopes.
    return filtered


def filter_ir(ir: dict[str, Any], allowed_sections: list[str]) -> tuple[dict[str, Any], int]:
    """Filter IR content to ``allowed_sections``.

    Supports :class:`SemanticDocument` IR (``front`` / ``body`` / ``back`` keys)
    and a flat ``elements[]`` list with per-element ``section`` tags.

    Returns ``(filtered_ir, dropped_element_count)``.
    """
    if "elements" in ir and isinstance(ir.get("elements"), list):
        return _filter_flat_ir(ir, allowed_sections)

    return _filter_partitioned_ir(ir, allowed_sections)


def resolve_scope(
    scope: str,
    template_schema: dict[str, Any] | TemplateSchema,
    ir: dict[str, Any],
) -> dict[str, Any]:
    """Normalize scope and filter both template schema and IR."""
    resolved_scope = normalize_scope(scope)
    allowed_sections = resolve_allowed_sections(resolved_scope)
    warnings: list[str] = []

    if isinstance(template_schema, TemplateSchema):
        schema_dict = template_schema.model_dump(mode="json")
    else:
        schema_dict = template_schema

    boundaries = schema_dict.get("section_boundaries", {})
    for section in allowed_sections:
        if section not in boundaries:
            warnings.append(
                f"template_schema has no section_boundaries entry for '{section}'"
            )

    filtered_template_schema = filter_template_schema(schema_dict, allowed_sections)
    filtered_ir, dropped_element_count = filter_ir(ir, allowed_sections)

    if resolved_scope == "back" and "back" not in boundaries:
        warnings.append("template has no <back> section_boundary; filtered IR back matter is empty")
    if resolved_scope == "front" and "front" not in boundaries:
        warnings.append("template has no <front> section_boundary; filtered IR front matter is empty")
    if resolved_scope == "body" and "body" not in boundaries:
        warnings.append("template has no <body> section_boundary; filtered IR body matter is empty")

    return {
        "resolved_scope": resolved_scope,
        "allowed_sections": allowed_sections,
        "filtered_template_schema": filtered_template_schema,
        "filtered_ir": filtered_ir,
        "dropped_element_count": dropped_element_count,
        "warnings": warnings,
    }


def _normalize_scope_text(raw_scope: str) -> str:
    text = raw_scope.strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\bonly\b", "", text)
    text = re.sub(r"\bmeta\b", "meta", text)
    return re.sub(r"\s+", " ", text).strip()


def _path_belongs_to_sections(path: str, allowed_sections: set[str]) -> bool:
    root = path.split("/", 1)[0]
    return root in allowed_sections


def _filter_tags(
    tags: dict[str, Any],
    allowed_sections: set[str],
    section_boundaries: dict[str, Any],
) -> dict[str, Any]:
    if allowed_sections == set(SECTION_ROOTS):
        return copy.deepcopy(tags)

    relevant: set[str] = {"article"}
    for section in allowed_sections:
        relevant.add(section)
        boundary = section_boundaries.get(section, {})
        if isinstance(boundary, dict):
            relevant.update(boundary.get("direct_children", []))
            relevant.update(boundary.get("descendants", []))
        else:
            relevant.update(getattr(boundary, "direct_children", []))
            relevant.update(getattr(boundary, "descendants", []))

    return {name: copy.deepcopy(spec) for name, spec in tags.items() if name in relevant}


def _empty_front() -> dict[str, Any]:
    return {
        "journal_header": None,
        "page_number": None,
        "title": None,
        "authors": [],
        "affiliations": [],
        "date_history": None,
        "corresponding_author": None,
        "abstract": None,
        "keywords": None,
        "other": [],
    }


def _empty_body() -> dict[str, Any]:
    return {"sections": [], "loose_paragraphs": []}


def _empty_back() -> dict[str, Any]:
    return {"reference_list": None, "references": [], "other": []}


def _count_front_nodes(front: dict[str, Any]) -> int:
    count = 0
    for key, value in front.items():
        if value is None:
            continue
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += 1
    return count


def _count_body_nodes(body: dict[str, Any]) -> int:
    count = len(body.get("loose_paragraphs", []))
    for section in body.get("sections", []):
        if not isinstance(section, dict):
            continue
        if section.get("heading_element"):
            count += 1
        count += len(section.get("paragraphs", []))
        count += len(section.get("content", []))
        count += _count_body_nodes({"sections": section.get("subsections", []), "loose_paragraphs": []})
    return count


def _count_back_nodes(back: dict[str, Any]) -> int:
    count = len(back.get("references", [])) + len(back.get("other", []))
    if back.get("reference_list"):
        count += 1
    return count


def _count_unknown_nodes(unknown: list[Any]) -> int:
    return len(unknown)


def _filter_partitioned_ir(ir: dict[str, Any], allowed_sections: list[str]) -> tuple[dict[str, Any], int]:
    allowed = set(allowed_sections)
    filtered = copy.deepcopy(ir)
    dropped = 0

    if "front" in ir and "front" not in allowed:
        dropped += _count_front_nodes(ir.get("front", {}))
        filtered["front"] = _empty_front()

    if "body" in ir and "body" not in allowed:
        dropped += _count_body_nodes(ir.get("body", {}))
        filtered["body"] = _empty_body()

    if "back" in ir and "back" not in allowed:
        dropped += _count_back_nodes(ir.get("back", {}))
        filtered["back"] = _empty_back()

    unknown = ir.get("unknown", [])
    if unknown:
        if allowed == set(SECTION_ROOTS):
            filtered["unknown"] = copy.deepcopy(unknown)
        else:
            dropped += _count_unknown_nodes(unknown)
            filtered["unknown"] = []
            for node in unknown:
                logger.debug("Dropped unknown IR node: %s", node.get("type", "unknown"))

    return filtered, dropped


def _filter_flat_ir(ir: dict[str, Any], allowed_sections: list[str]) -> tuple[dict[str, Any], int]:
    allowed = set(allowed_sections)
    filtered = copy.deepcopy(ir)
    kept: list[dict[str, Any]] = []
    dropped = 0

    for element in ir.get("elements", []):
        section = element.get("section")
        if section in allowed:
            kept.append(element)
        else:
            dropped += 1
            if section is None:
                logger.debug("Dropped IR element with missing section tag: %s", element.get("type"))
            else:
                logger.debug("Dropped IR element in disallowed section %s: %s", section, element.get("type"))

    filtered["elements"] = kept
    return filtered, dropped
