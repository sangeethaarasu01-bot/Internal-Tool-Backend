"""Post-process LLM semantic mapping before XML generation (LLM path only)."""

from __future__ import annotations

from typing import Any

from app.models.semantic_mapping import SemanticMappingBody
from app.services.ir_semantic_adapter import ensure_semantic_mapping_body


def normalize_llm_semantic_mapping(
    mapping: SemanticMappingBody | dict[str, Any],
) -> SemanticMappingBody:
    """
    Validate and coerce LLM mapping JSON into the application contract.

    Does not alter extracted IR or heuristic mappings. Reference authority
    remains with ``fill_back_references_from_ir`` after normalization.
    """
    return ensure_semantic_mapping_body(mapping)
