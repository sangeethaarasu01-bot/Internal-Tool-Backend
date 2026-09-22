"""Anthropic Claude API implementation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from anthropic import APIStatusError, AsyncAnthropic, AuthenticationError

from app.config import settings
from app.llm.client import LLMResponse
from app.llm.mock_fallback import mock_complete_response, should_use_offline_fallback
from app.llm.openai_provider import _mock_json
from app.utils.logger import logger

# USD per 1M tokens (approximate)
_COST = {
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "claude-3-5-haiku-20241022": (0.8, 4.0),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    for key, (inp, out) in _COST.items():
        if key in model:
            return (tokens_in * inp + tokens_out * out) / 1_000_000
    return (tokens_in * 3 + tokens_out * 15) / 1_000_000


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def anthropic_complete(
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> LLMResponse:
    if not api_key:
        text = _mock_json(user) if json_mode else user[:2000]
        if not json_mode and "TEMPLATE XML" in user:
            start = user.find("TEMPLATE XML")
            tpl = user[start:] if start >= 0 else user
            if "<article" in tpl:
                idx = tpl.find("<article")
                text = tpl[idx : idx + 8000]
        ti = _approx_tokens(system + user)
        to = _approx_tokens(text)
        return LLMResponse(text=text, tokens_in=ti, tokens_out=to, cost_usd=0.0, model=model)

    client = AsyncAnthropic(api_key=api_key)
    user_content = user
    if json_mode:
        user_content = user + "\n\nRespond with valid JSON only, no markdown."

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
    except (APIStatusError, AuthenticationError) as exc:
        if settings.LLM_FALLBACK_MOCK and should_use_offline_fallback(exc):
            logger.warning("Anthropic billing/auth error — offline fallback: {}", exc)
            return mock_complete_response(model, system, user, json_mode)
        raise
    text = ""
    for block in resp.content:
        if block.type == "text":
            text += block.text
    ti = resp.usage.input_tokens if resp.usage else _approx_tokens(system + user)
    to = resp.usage.output_tokens if resp.usage else _approx_tokens(text)
    if json_mode:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    cost = _estimate_cost(model, ti, to)
    return LLMResponse(text=text, tokens_in=ti, tokens_out=to, cost_usd=cost, model=model)


async def anthropic_stream(
    api_key: str,
    model: str,
    system: str,
    user: str,
    on_token: Callable[[str], Awaitable[None] | None],
) -> LLMResponse:
    if not api_key:
        text = ""
        for ch in "claude mock":
            if callable(on_token):
                r = on_token(ch)
                if r is not None:
                    await r
            text += ch
        return LLMResponse(text=text, tokens_in=0, tokens_out=0, cost_usd=0.0, model=model)

    client = AsyncAnthropic(api_key=api_key)
    parts: list[str] = []
    async with client.messages.stream(
        model=model,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        async for text in stream.text_stream:
            parts.append(text)
            if callable(on_token):
                r = on_token(text)
                if r is not None:
                    await r
    full = "".join(parts)
    ti = _approx_tokens(system + user)
    to = _approx_tokens(full)
    return LLMResponse(
        text=full,
        tokens_in=ti,
        tokens_out=to,
        cost_usd=_estimate_cost(model, ti, to),
        model=model,
    )
