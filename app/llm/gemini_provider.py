"""Google Gemini API implementation (Generative Language API)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import httpx

from app.config import settings
from app.llm.client import LLMResponse
from app.llm.mock_fallback import mock_complete_response, should_use_offline_fallback
from app.llm.openai_provider import _mock_json
from app.utils.logger import logger

# USD per 1M tokens (approximate; Gemini 2.5 Flash)
_COST = {
    "gemini-2.5-flash": (0.15, 0.6),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.0),
}


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    for key, (inp, out) in _COST.items():
        if key in model:
            return (tokens_in * inp + tokens_out * out) / 1_000_000
    return (tokens_in * 0.15 + tokens_out * 0.6) / 1_000_000


def _model_resource(model: str) -> str:
    name = (model or "gemini-2.5-flash").strip()
    if name.startswith("models/"):
        return name
    return f"models/{name}"


def _strip_json_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            return "\n".join(lines[1:-1])
        return "\n".join(lines[1:])
    return text


async def gemini_complete(
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

    resource = _model_resource(model)
    base = settings.GEMINI_API_BASE.rstrip("/")
    url = f"{base}/{resource}:generateContent"
    generation_config: dict = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if json_mode:
        generation_config["responseMimeType"] = "application/json"

    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation_config,
    }
    if system.strip():
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)
    retryable_status = frozenset({429, 500, 502, 503, 504})
    max_attempts = 4
    response: httpx.Response | None = None
    last_detail = ""

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(max_attempts):
                try:
                    response = await client.post(
                        url,
                        params={"key": api_key},
                        json=payload,
                    )
                except httpx.HTTPError as exc:
                    if attempt + 1 < max_attempts and should_use_offline_fallback(exc):
                        await asyncio.sleep(min(2**attempt, 8))
                        continue
                    if settings.LLM_FALLBACK_MOCK and should_use_offline_fallback(exc):
                        logger.warning("Gemini request failed — offline fallback: {}", exc)
                        return mock_complete_response(model, system, user, json_mode)
                    raise

                if response.status_code < 400:
                    break
                last_detail = response.text[:500]
                if response.status_code in retryable_status and attempt + 1 < max_attempts:
                    logger.warning(
                        "Gemini HTTP {} — retry {}/{}",
                        response.status_code,
                        attempt + 1,
                        max_attempts - 1,
                    )
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                break
    except httpx.HTTPError:
        raise

    if response is None:
        raise RuntimeError("Gemini API returned no response")

    if response.status_code >= 400:
        detail = last_detail or response.text[:500]
        exc = RuntimeError(f"Gemini API error {response.status_code}: {detail}")
        if settings.LLM_FALLBACK_MOCK and should_use_offline_fallback(exc):
            logger.warning("Gemini API error — offline fallback: {}", detail)
            return mock_complete_response(model, system, user, json_mode)
        raise exc

    try:
        data = response.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected Gemini response: {response.text[:300]}") from exc

    if json_mode:
        text = _strip_json_markdown(text)

    usage = data.get("usageMetadata") or {}
    ti = int(usage.get("promptTokenCount") or _approx_tokens(system + user))
    to = int(usage.get("candidatesTokenCount") or _approx_tokens(text))
    cost = _estimate_cost(model, ti, to)
    return LLMResponse(text=text, tokens_in=ti, tokens_out=to, cost_usd=cost, model=model)


async def gemini_stream(
    api_key: str,
    model: str,
    system: str,
    user: str,
    on_token: Callable[[str], Awaitable[None] | None],
) -> LLMResponse:
    resp = await gemini_complete(
        api_key,
        model,
        system,
        user,
        temperature=0.0,
        max_tokens=8000,
        json_mode=False,
    )
    if callable(on_token) and resp.text:
        for ch in resp.text:
            r = on_token(ch)
            if r is not None:
                await r
    return resp
