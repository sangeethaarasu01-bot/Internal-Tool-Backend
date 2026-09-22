"""LLM provider abstraction."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from app.config import settings
from app.utils.logger import logger


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str
    offline_fallback: bool = False


@dataclass
class LLMClient:
    provider: Literal["openai", "anthropic"]
    model: str
    api_key: str
    total_cost: float = field(default=0.0)
    total_tokens: int = field(default=0)
    offline_fallback_used: bool = field(default=False)

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 8000,
        json_mode: bool = False,
    ) -> LLMResponse:
        start = time.perf_counter()
        from app.llm.mock_fallback import mock_complete_response, should_use_offline_fallback

        try:
            if self.provider == "openai":
                from app.llm.openai_provider import openai_complete

                resp = await openai_complete(
                    self.api_key,
                    self.model,
                    system,
                    user,
                    temperature,
                    max_tokens,
                    json_mode,
                )
            else:
                from app.llm.anthropic_provider import anthropic_complete

                resp = await anthropic_complete(
                    self.api_key,
                    self.model,
                    system,
                    user,
                    temperature,
                    max_tokens,
                    json_mode,
                )
        except Exception as exc:
            if settings.LLM_FALLBACK_MOCK and should_use_offline_fallback(exc):
                logger.warning(
                    "LLM API error ({}), using offline fallback: {}",
                    self.provider,
                    exc,
                )
                self.offline_fallback_used = True
                resp = mock_complete_response(self.model, system, user, json_mode)
            else:
                raise
        if resp.offline_fallback:
            self.offline_fallback_used = True
        duration = time.perf_counter() - start
        self.total_cost += resp.cost_usd
        self.total_tokens += resp.tokens_in + resp.tokens_out
        logger.info(
            "LLM complete provider={} model={} tokens_in={} tokens_out={} cost=${:.4f} duration={:.2f}s",
            self.provider,
            resp.model,
            resp.tokens_in,
            resp.tokens_out,
            resp.cost_usd,
            duration,
        )
        logger.debug("LLM user prompt (truncated): {}", user[:500])
        logger.debug("LLM response (truncated): {}", resp.text[:500])
        return resp

    async def stream(
        self,
        system: str,
        user: str,
        on_token: Callable[[str], Awaitable[None] | None],
    ) -> LLMResponse:
        if self.provider == "openai":
            from app.llm.openai_provider import openai_stream

            resp = await openai_stream(self.api_key, self.model, system, user, on_token)
        else:
            from app.llm.anthropic_provider import anthropic_stream

            resp = await anthropic_stream(self.api_key, self.model, system, user, on_token)
        self.total_cost += resp.cost_usd
        self.total_tokens += resp.tokens_in + resp.tokens_out
        return resp

    def with_model(self, model: str) -> LLMClient:
        return LLMClient(
            provider=self.provider,
            model=model,
            api_key=self.api_key,
            total_cost=self.total_cost,
            total_tokens=self.total_tokens,
        )


def create_llm_client(model: str | None = None) -> LLMClient:
    provider = settings.LLM_PROVIDER
    m = model or settings.LLM_MODEL_GENERATION
    key = settings.OPENAI_API_KEY if provider == "openai" else settings.ANTHROPIC_API_KEY
    return LLMClient(provider=provider, model=m, api_key=key)
