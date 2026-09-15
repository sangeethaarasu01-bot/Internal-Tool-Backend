"""LLM provider protocol for semantic mapping."""

from __future__ import annotations

from typing import Protocol


class LLMConfigurationError(RuntimeError):
    """Raised when LLM provider is not configured."""


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider call fails."""


class LLMProvider(Protocol):
    """Provider abstraction for JSON-oriented LLM completion."""

    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...

    def complete(self, *, system_prompt: str, user_message: str) -> str:
        """Return raw text completion from the model."""
        ...
