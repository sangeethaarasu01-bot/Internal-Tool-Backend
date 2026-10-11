"""Orchestrate heuristic vs optional LLM semantic mapping for XML generation.

Heuristic mapping is isolated in :func:`build_heuristic_semantic_mapping` and must
remain behavior-identical to the legacy IR adapter path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.models.semantic_mapping import SemanticMappingBody
from app.services.ir_semantic_adapter import (
    ensure_semantic_mapping_body,
    fill_back_references_from_ir,
    ir_to_semantic_mapping,
)
from app.services.llm.providers.base import LLMConfigurationError
from app.services.llm.providers.factory import is_llm_configured
from app.services.llm_mapping_normalize import normalize_llm_semantic_mapping
from app.services.llm_semantic_mapper import SemanticMappingError, map_semantic_content

logger = logging.getLogger(__name__)

_HEURISTIC_HINT = (
    "Generated using deterministic IR adapter (no LLM). "
    "Set use_llm=true for template-aware LLM mapping."
)
_LLM_FALLBACK_HINT = (
    "LLM mapping failed (Claude timeout or API error). "
    "XML was generated using deterministic extraction instead."
)


@dataclass(frozen=True)
class MappingResolutionResult:
    mapping_body: SemanticMappingBody
    mapping_source: str
    prompt_version: str | None = None
    warnings: list[str] = field(default_factory=list)
    unmapped_count: int = 0
    semantic_record: dict[str, Any] | None = None
    llm_attempted: bool = False
    llm_succeeded: bool = False


def build_heuristic_semantic_mapping(ir: dict[str, Any]) -> SemanticMappingBody:
    """Deterministic IR → semantic mapping (heuristic mode)."""
    return ir_to_semantic_mapping(ir)


def finalize_mapping_for_xml(
    mapping_body: SemanticMappingBody | dict[str, Any],
    ir: dict[str, Any],
) -> SemanticMappingBody:
    """Shared post-processing for both heuristic and LLM mapping sources."""
    body = ensure_semantic_mapping_body(mapping_body)
    return fill_back_references_from_ir(body, ir)


def resolve_semantic_mapping_for_generate_xml(
    *,
    extraction_id: str,
    resolved_scope: str,
    filtered_ir: dict[str, Any],
    filtered_template_schema: dict[str, Any] | None,
    use_llm: bool,
    llm_fallback: bool,
) -> MappingResolutionResult:
    """
    Choose heuristic or LLM mapping without modifying extraction or XML generators.

    When ``use_llm`` is false (default), only :func:`build_heuristic_semantic_mapping`
    runs. When true, calls the LLM mapper and optionally falls back to heuristic.
    """
    warnings: list[str] = []
    llm_attempted = False
    llm_succeeded = False

    if use_llm and not is_llm_configured():
        logger.warning(
            "LLM not configured for %s; using heuristic IR adapter (no API key)",
            extraction_id,
        )
        use_llm = False
        warnings.append("LLM not configured. Using heuristic IR adapter.")

    if not use_llm:
        mapping_body = build_heuristic_semantic_mapping(filtered_ir)
        warnings.append(_HEURISTIC_HINT)
        return MappingResolutionResult(
            mapping_body=mapping_body,
            mapping_source="ir_adapter",
            warnings=warnings,
        )

    llm_attempted = True
    try:
        mapping_result = map_semantic_content(
            document_id=extraction_id,
            scope=resolved_scope,
            ir=filtered_ir,
            template_schema=filtered_template_schema or {},
            max_retries=1 if llm_fallback else 2,
        )
        mapping_body = normalize_llm_semantic_mapping(mapping_result.mapping)
        llm_succeeded = True
        return MappingResolutionResult(
            mapping_body=mapping_body,
            mapping_source="llm",
            prompt_version=mapping_result.prompt_version,
            warnings=[*warnings, *mapping_result.warnings],
            unmapped_count=len(mapping_result.unmapped_content),
            semantic_record=mapping_result.model_dump(mode="json"),
            llm_attempted=True,
            llm_succeeded=True,
        )
    except LLMConfigurationError:
        raise
    except SemanticMappingError as exc:
        if not llm_fallback:
            raise
        logger.info(
            "LLM mapping failed for %s; falling back to IR adapter: %s",
            extraction_id,
            exc,
        )
        mapping_body = build_heuristic_semantic_mapping(filtered_ir)
        warnings.append(_LLM_FALLBACK_HINT)
        return MappingResolutionResult(
            mapping_body=mapping_body,
            mapping_source="ir_adapter_fallback",
            warnings=warnings,
            llm_attempted=True,
            llm_succeeded=False,
        )
