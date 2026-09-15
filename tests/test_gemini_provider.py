"""Tests for Gemini LLM provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.llm.providers.base import LLMConfigurationError, LLMProviderError
from app.services.llm.providers.factory import get_llm_provider, is_llm_configured
from app.services.llm.providers.gemini_provider import GeminiProvider


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(LLMConfigurationError, match="GEMINI_API_KEY"):
        GeminiProvider(api_key="", model="gemini-2.0-flash")


@patch("app.services.llm.providers.gemini_provider.httpx.Client")
def test_gemini_provider_complete(mock_client_cls: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"mapping": {}}'}]}}],
    }
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    mock_client_cls.return_value = client

    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")
    result = provider.complete(system_prompt="You are a mapper.", user_message='{"ir": {}}')
    assert result.startswith('{"mapping"')
    assert provider.provider_name == "gemini"
    assert provider.model_name == "gemini-2.0-flash"


@patch("app.services.llm.providers.gemini_provider.httpx.Client")
def test_gemini_provider_api_error(mock_client_cls: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 403
    response.text = "API key invalid"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    mock_client_cls.return_value = client

    provider = GeminiProvider(api_key="bad-key", model="gemini-2.0-flash")
    with pytest.raises(LLMProviderError, match="403"):
        provider.complete(system_prompt="sys", user_message="user")


@patch("app.config.llm_config.LLM_PROVIDER", "gemini")
@patch("app.config.llm_config.GEMINI_API_KEY", "secret")
@patch("app.config.llm_config.LLM_MODEL", "gemini-2.0-flash")
def test_factory_returns_gemini() -> None:
    provider = get_llm_provider()
    assert provider.provider_name == "gemini"
    assert is_llm_configured() is True
