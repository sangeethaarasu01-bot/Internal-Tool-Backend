"""Tests for Anthropic Claude LLM provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.llm.providers.anthropic_provider import AnthropicProvider
from app.services.llm.providers.base import LLMConfigurationError, LLMProviderError
from app.services.llm.providers.factory import get_llm_provider, is_llm_configured


def test_anthropic_provider_requires_api_key() -> None:
    with pytest.raises(LLMConfigurationError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(api_key="", model="claude-sonnet-4-20250514")


@patch("app.services.llm.providers.anthropic_provider.httpx.Client")
def test_anthropic_provider_complete(mock_client_cls: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "content": [{"type": "text", "text": '{"mapping": {}}'}],
    }
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    mock_client_cls.return_value = client

    provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-20250514")
    result = provider.complete(system_prompt="You are a mapper.", user_message='{"ir": {}}')
    assert result.startswith('{"mapping"')
    assert provider.provider_name == "anthropic"
    assert provider.model_name == "claude-sonnet-4-20250514"


@patch("app.services.llm.providers.anthropic_provider.httpx.Client")
def test_anthropic_provider_api_error(mock_client_cls: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 403
    response.text = "API key invalid"
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    mock_client_cls.return_value = client

    provider = AnthropicProvider(api_key="bad-key", model="claude-sonnet-4-20250514")
    with pytest.raises(LLMProviderError, match="403"):
        provider.complete(system_prompt="sys", user_message="user")


@patch("app.config.llm_config.LLM_PROVIDER", "anthropic")
@patch("app.config.llm_config.ANTHROPIC_API_KEY", "secret")
@patch("app.config.llm_config.LLM_MODEL", "claude-sonnet-4-20250514")
def test_factory_returns_anthropic() -> None:
    provider = get_llm_provider()
    assert provider.provider_name == "anthropic"
    assert is_llm_configured() is True
