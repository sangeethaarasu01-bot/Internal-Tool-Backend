"""Google Gemini provider for semantic mapping."""

from __future__ import annotations

import json
import logging

import httpx

from app.config.llm_config import GEMINI_REQUEST_TIMEOUT
from app.services.llm.providers.base import LLMConfigurationError, LLMProviderError

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini ``generateContent`` API provider."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_base: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        if not api_key:
            raise LLMConfigurationError(
                "GEMINI_API_KEY is not configured. Set the environment variable to enable semantic mapping."
            )
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        url = f"{self._api_base}/models/{self._model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(
            connect=30.0,
            read=GEMINI_REQUEST_TIMEOUT,
            write=60.0,
            pool=30.0,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Gemini request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise LLMProviderError(f"Gemini API error {response.status_code}: {detail}")

        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            return parts[0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"Unexpected Gemini response shape: {response.text[:300]}") from exc
