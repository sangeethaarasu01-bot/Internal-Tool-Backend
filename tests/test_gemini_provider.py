"""Tests for Gemini LLM provider wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.llm.providers.base import LLMConfigurationError
from app.services.llm.providers.factory import get_llm_provider
from app.services.llm.providers.gemini_provider import GeminiProvider


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(LLMConfigurationError):
        GeminiProvider(api_key="", model="gemini-2.5-flash")


@patch("app.services.llm.providers.gemini_provider.httpx.Client")
def test_gemini_provider_complete(mock_client_cls: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = mock_response
    mock_client_cls.return_value = mock_client

    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
    assert provider.provider_name == "gemini"
    text = provider.complete(system_prompt="sys", user_message="user")
    assert '"ok": true' in text


@patch("app.config.llm_config.LLM_PROVIDER", "gemini")
@patch("app.config.llm_config.GEMINI_API_KEY", "test-key")
@patch("app.config.llm_config.LLM_MODEL", "gemini-2.5-flash")
def test_factory_returns_gemini() -> None:
    provider = get_llm_provider()
    assert provider.provider_name == "gemini"
