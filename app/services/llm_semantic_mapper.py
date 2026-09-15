"""LLM semantic mapping: scoped IR + template schema → structured semantic JSON.

The LLM NEVER generates XML. Output is JSON only, validated by Pydantic.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config.llm_config import (
    LLM_MAX_RETRIES,
    SEMANTIC_MAPPING_PROMPT_VERSION,
    load_semantic_mapping_system_prompt,
)
from app.models.semantic_mapping import SemanticMappingResult
from app.services.llm.call_logger import log_llm_call
from app.services.llm.payload_compact import compact_ir_for_llm, compact_template_schema_for_llm
from app.services.llm.providers.base import LLMConfigurationError, LLMProvider, LLMProviderError
from app.services.llm.providers.factory import get_llm_provider
from app.services.llm.response_parser import LLMResponseParseError, parse_llm_mapping_response

logger = logging.getLogger(__name__)

STRICT_JSON_RETRY_SUFFIX = (
    "\n\nSTRICT REMINDER: Your previous response was rejected. "
    "Return ONLY a raw JSON object. No XML tags. No Markdown fences. No commentary."
)


def _is_timeout_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "timed out" in message or "timeout" in message


class SemanticMappingError(RuntimeError):
    """Raised when semantic mapping fails."""


def build_user_payload(
    *,
    document_id: str,
    scope: str,
    ir: dict[str, Any],
    template_schema: dict[str, Any],
) -> dict[str, Any]:
    """Build the user message payload for the LLM."""
    return {
        "document_id": document_id,
        "scope": scope,
        "ir": compact_ir_for_llm(ir),
        "template_schema": compact_template_schema_for_llm(template_schema),
    }


def map_semantic_content(
    *,
    document_id: str,
    scope: str,
    ir: dict[str, Any],
    template_schema: dict[str, Any],
    provider: LLMProvider | None = None,
    prompt_version: str = SEMANTIC_MAPPING_PROMPT_VERSION,
    max_retries: int | None = None,
) -> SemanticMappingResult:
    """Map scoped IR + template schema to structured semantic JSON via LLM."""
    retry_limit = max_retries if max_retries is not None else LLM_MAX_RETRIES
    llm = provider or get_llm_provider()
    system_prompt = load_semantic_mapping_system_prompt(prompt_version)
    user_payload = build_user_payload(
        document_id=document_id,
        scope=scope,
        ir=ir,
        template_schema=template_schema,
    )
    user_message = json.dumps(user_payload, ensure_ascii=False, default=str)
    logger.info(
        "Semantic mapping payload for %s: %s chars (provider=%s, retries=%s)",
        document_id,
        len(user_message),
        llm.provider_name,
        retry_limit,
    )

    last_error: Exception | None = None
    raw_response: str | None = None
    start = time.perf_counter()

    for attempt in range(retry_limit):
        attempt_prompt = system_prompt
        if attempt > 0:
            attempt_prompt = system_prompt + STRICT_JSON_RETRY_SUFFIX

        try:
            raw_response = llm.complete(system_prompt=attempt_prompt, user_message=user_message)
            payload = parse_llm_mapping_response(raw_response)
            latency_ms = (time.perf_counter() - start) * 1000
            log_llm_call(
                document_id=document_id,
                prompt_version=prompt_version,
                provider=llm.provider_name,
                model=llm.model_name,
                input_payload=user_payload,
                output_text=raw_response,
                success=True,
                latency_ms=latency_ms,
            )
            return SemanticMappingResult(
                document_id=document_id,
                scope=scope,
                prompt_version=prompt_version,
                mapping=payload.mapping,
                unmapped_content=payload.unmapped_content,
                warnings=payload.warnings,
            )
        except (LLMProviderError, LLMResponseParseError) as exc:
            last_error = exc
            logger.warning(
                "Semantic mapping attempt %s/%s failed for %s: %s",
                attempt + 1,
                retry_limit,
                document_id,
                exc,
            )
            if _is_timeout_error(exc):
                logger.warning(
                    "Skipping further LLM retries for %s after timeout",
                    document_id,
                )
            if _is_timeout_error(exc) or attempt + 1 >= retry_limit:
                latency_ms = (time.perf_counter() - start) * 1000
                log_llm_call(
                    document_id=document_id,
                    prompt_version=prompt_version,
                    provider=llm.provider_name,
                    model=llm.model_name,
                    input_payload=user_payload,
                    output_text=raw_response,
                    success=False,
                    error=str(exc),
                    latency_ms=latency_ms,
                )
                raise SemanticMappingError(str(exc)) from exc

    raise SemanticMappingError(str(last_error or "Semantic mapping failed"))
