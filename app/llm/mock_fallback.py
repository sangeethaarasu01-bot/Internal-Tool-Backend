"""Offline LLM responses when API keys are missing or billing fails."""

from __future__ import annotations

from app.llm.client import LLMResponse
from app.llm.openai_provider import _mock_json


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def mock_complete_response(
    model: str,
    system: str,
    user: str,
    json_mode: bool,
) -> LLMResponse:
    if json_mode:
        text = _mock_json(user)
    elif "TEMPLATE XML" in user:
        start = user.find("TEMPLATE XML")
        tpl = user[start:] if start >= 0 else user
        if "<article" in tpl:
            idx = tpl.find("<article")
            text = tpl[idx : idx + 8000]
        else:
            text = tpl[:8000]
    else:
        text = user[:2000]
    ti = _approx_tokens(system + user)
    to = _approx_tokens(text)
    return LLMResponse(
        text=text,
        tokens_in=ti,
        tokens_out=to,
        cost_usd=0.0,
        model=f"{model}+offline-fallback",
        offline_fallback=True,
    )


def should_use_offline_fallback(exc: BaseException) -> bool:
    msg = str(exc).lower()
    needles = (
        "credit balance",
        "insufficient",
        "billing",
        "quota",
        "rate limit",
        "invalid_api_key",
        "authentication",
        "unauthorized",
        "401",
        "402",
        "429",
    )
    return any(n in msg for n in needles)
