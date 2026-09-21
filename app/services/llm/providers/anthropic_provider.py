"""Anthropic Claude provider for semantic mapping."""

from __future__ import annotations

import json
import logging

import httpx

from app.config.llm_config import ANTHROPIC_REQUEST_TIMEOUT
from app.services.llm.providers.base import LLMConfigurationError, LLMProviderError

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    """Anthropic Messages API provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str = "https://api.anthropic.com/v1",
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is not configured. Set the environment variable to enable semantic mapping."
            )
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        url = f"{self._api_base}/messages"
        payload = {
            "model": self._model,
            "max_tokens": 16384,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(
            connect=30.0,
            read=ANTHROPIC_REQUEST_TIMEOUT,
            write=60.0,
            pool=30.0,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Anthropic request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise LLMProviderError(f"Anthropic API error {response.status_code}: {detail}")

        try:
            data = response.json()
            for block in data["content"]:
                if block.get("type") == "text":
                    return block["text"]
            raise KeyError("no text block in content")
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMProviderError(
                f"Unexpected Anthropic response shape: {response.text[:300]}"
            ) from exc
