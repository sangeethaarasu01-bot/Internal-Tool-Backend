"""OpenAI API implementation."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import tiktoken
from openai import AsyncOpenAI

from app.llm.client import LLMResponse

# USD per 1M tokens (approximate)
_COST = {
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    key = model if model in _COST else "gpt-4o-mini"
    inp, out = _COST[key]
    return (tokens_in * inp + tokens_out * out) / 1_000_000


def _count_tokens(model: str, text: str) -> int:
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


async def openai_complete(
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> LLMResponse:
    client = AsyncOpenAI(api_key=api_key or "sk-mock")
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if not api_key:
        text = _mock_json(user) if json_mode else "<article/>"
        ti = _count_tokens(model, system + user)
        to = _count_tokens(model, text)
        return LLMResponse(text=text, tokens_in=ti, tokens_out=to, cost_usd=0.0, model=model)
    resp = await client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    ti = resp.usage.prompt_tokens if resp.usage else _count_tokens(model, system + user)
    to = resp.usage.completion_tokens if resp.usage else _count_tokens(model, text)
    cost = _estimate_cost(model, ti, to)
    return LLMResponse(text=text, tokens_in=ti, tokens_out=to, cost_usd=cost, model=model)


async def openai_stream(
    api_key: str,
    model: str,
    system: str,
    user: str,
    on_token: Callable[[str], Awaitable[None] | None],
) -> LLMResponse:
    client = AsyncOpenAI(api_key=api_key or "sk-mock")
    if not api_key:
        text = ""
        for ch in "mock stream":
            if callable(on_token):
                r = on_token(ch)
                if r is not None:
                    await r
            text += ch
        return LLMResponse(text=text, tokens_in=0, tokens_out=0, cost_usd=0.0, model=model)
    stream = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=True,
    )
    parts: list[str] = []
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        parts.append(delta)
        if delta and callable(on_token):
            r = on_token(delta)
            if r is not None:
                await r
    text = "".join(parts)
    ti = _count_tokens(model, system + user)
    to = _count_tokens(model, text)
    return LLMResponse(
        text=text,
        tokens_in=ti,
        tokens_out=to,
        cost_usd=_estimate_cost(model, ti, to),
        model=model,
    )


def _mock_json(user: str) -> str:
    if "Schema Map" in user or "schema" in user.lower()[:200]:
        return json.dumps(
            {
                "root_tag": "article",
                "namespaces": {"xmlns": "http://www.w3.org/1998/Math/MathML"},
                "doctype": None,
                "elements": [
                    {
                        "xpath": "article/front/article-meta/title-group/article-title",
                        "tag": "article-title",
                        "semantic": "paper_title",
                        "cardinality": "single",
                        "data_type": "string",
                        "required": True,
                        "attributes": {},
                        "sample": "",
                        "children": [],
                        "notes": "",
                    }
                ],
            }
        )
    if "semantic matching" in user.lower() or "Match extracted" in user:
        return json.dumps(
            {
                "mappings": [
                    {
                        "xml_xpath": "front/article-meta/title-group/article-title",
                        "xml_tag": "article-title",
                        "pdf_field": "title",
                        "transform": "none",
                        "transform_arg": None,
                        "confidence": 0.95,
                        "reasoning": "Title match",
                    },
                    {
                        "xml_xpath": "front/article-meta/contrib-group/contrib",
                        "xml_tag": "contrib",
                        "pdf_field": "authors[]",
                        "transform": "loop",
                        "transform_arg": None,
                        "confidence": 0.9,
                        "reasoning": "Authors",
                    },
                    {
                        "xml_xpath": "front/article-meta/abstract",
                        "xml_tag": "abstract",
                        "pdf_field": "abstract",
                        "transform": "none",
                        "transform_arg": None,
                        "confidence": 0.92,
                        "reasoning": "Abstract",
                    },
                ],
                "unmapped_xml": [],
                "unmapped_pdf": [],
                "warnings": [],
            }
        )
    if "REFERENCE" in user:
        return json.dumps(
            {
                "publication_type": "periodical",
                "authors": [{"given": "H.", "surname": "Sung"}],
                "article_title": "Sample",
                "source": "IEEE",
                "volume": "1",
                "issue": "1",
                "fpage": "1",
                "lpage": "10",
                "month": "Jan",
                "year": "2020",
                "doi": "",
                "url": "",
                "extra_xml": "",
            }
        )
    return json.dumps({"ok": True})
