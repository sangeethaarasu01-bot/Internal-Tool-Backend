"""Async Gemini client integration."""

from __future__ import annotations

import pytest

from app.config import settings
from app.llm.client import LLMClient


@pytest.mark.asyncio
async def test_gemini_client_mock_without_api_key() -> None:
    llm = LLMClient(provider="gemini", model="gemini-2.5-flash", api_key="")
    resp = await llm.complete(
        system="Return JSON",
        user='{"mappings": []}',
        json_mode=True,
    )
    assert resp.text
    assert resp.model == "gemini-2.5-flash"


def test_resolve_llm_model_uses_gemini_model_when_provider_gemini() -> None:
    original = settings.LLM_PROVIDER
    try:
        settings.LLM_PROVIDER = "gemini"
        settings.GEMINI_MODEL = "gemini-2.5-flash"
        assert settings.resolve_llm_model("matching") == "gemini-2.5-flash"
    finally:
        settings.LLM_PROVIDER = original
