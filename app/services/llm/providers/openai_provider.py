"""OpenAI chat-completions provider for semantic mapping."""

from __future__ import annotations

import json
import logging

import httpx

from app.config.llm_config import LLM_REQUEST_TIMEOUT
from app.services.llm.providers.base import LLMConfigurationError, LLMProviderError

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI-compatible chat completions provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str = "https://api.openai.com/v1",
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not configured. Set the environment variable to enable semantic mapping."
            )
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        url = f"{self._api_base}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=LLM_REQUEST_TIMEOUT) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"OpenAI request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise LLMProviderError(f"OpenAI API error {response.status_code}: {detail}")

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"Unexpected OpenAI response shape: {response.text[:300]}") from exc
