"""Parse and validate raw LLM responses for semantic mapping."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.semantic_mapping import LlmMappingPayload

_XML_MARKERS = re.compile(r"<\?xml|<article[\s>]|</article>|<ref[\s>]|</ref>|<table-wrap", re.I)
_MARKDOWN_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMResponseParseError(ValueError):
    """Raised when LLM output cannot be parsed as valid semantic JSON."""


def reject_non_json_formats(raw: str) -> None:
    """Reject XML and obvious Markdown-wrapped responses."""
    stripped = raw.strip()
    if not stripped:
        raise LLMResponseParseError("LLM returned empty response")
    if _XML_MARKERS.search(stripped):
        raise LLMResponseParseError("LLM response contains XML — only JSON is allowed")
    if stripped.startswith("```") or stripped.endswith("```"):
        raise LLMResponseParseError("LLM response is Markdown-wrapped — only raw JSON is allowed")


def extract_json_text(raw: str) -> str:
    """Return JSON text from a raw model response."""
    reject_non_json_formats(raw)
    text = raw.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    raise LLMResponseParseError("LLM response is not a JSON object")


def parse_llm_mapping_response(raw: str) -> LlmMappingPayload:
    """Parse and validate LLM JSON into a mapping payload model."""
    json_text = extract_json_text(raw)
    try:
        data: dict[str, Any] = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise LLMResponseParseError(f"Invalid JSON from LLM: {exc}") from exc

    if not isinstance(data, dict):
        raise LLMResponseParseError("LLM response must be a JSON object")

    unexpected = set(data.keys()) - {"mapping", "unmapped_content", "warnings"}
    if unexpected:
        raise LLMResponseParseError(
            f"LLM response contains unexpected top-level keys: {sorted(unexpected)}"
        )

    if "mapping" not in data:
        raise LLMResponseParseError("LLM response missing required field: mapping")

    mapping = data.get("mapping")
    if not isinstance(mapping, dict):
        raise LLMResponseParseError("mapping must be a JSON object")

    for section in ("front", "body", "back"):
        if section not in mapping:
            raise LLMResponseParseError(f"mapping missing required section: {section}")

    if not isinstance(mapping.get("body"), list):
        raise LLMResponseParseError("mapping.body must be a JSON array")

    try:
        return LlmMappingPayload.model_validate(data)
    except Exception as exc:
        raise LLMResponseParseError(f"LLM response failed schema validation: {exc}") from exc
