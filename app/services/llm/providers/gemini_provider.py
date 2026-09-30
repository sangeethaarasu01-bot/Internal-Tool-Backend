"""Google Gemini provider for semantic mapping."""

from __future__ import annotations

import json
import logging

import httpx

from app.config import llm_config
from app.services.llm.providers.base import LLMConfigurationError, LLMProviderError

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Gemini generateContent API provider (sync httpx for mapping workflow)."""

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
        self._model = model.strip()
        self._api_base = api_base.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def _model_resource(self) -> str:
        if self._model.startswith("models/"):
            return self._model
        return f"models/{self._model}"

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        url = f"{self._api_base}/{self._model_resource()}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 16384,
                "responseMimeType": "application/json",
            },
        }
        if system_prompt.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        timeout = httpx.Timeout(
            connect=30.0,
            read=llm_config.LLM_REQUEST_TIMEOUT,
            write=60.0,
            pool=30.0,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, params={"key": self._api_key}, json=payload)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Gemini request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise LLMProviderError(f"Gemini API error {response.status_code}: {detail}")

        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMProviderError(
                f"Unexpected Gemini response shape: {response.text[:300]}"
            ) from exc
