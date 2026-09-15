"""Factory for LLM provider instances."""

from __future__ import annotations

from app.config import llm_config
from app.services.llm.providers.base import LLMConfigurationError, LLMProvider
from app.services.llm.providers.gemini_provider import GeminiProvider
from app.services.llm.providers.openai_provider import OpenAIProvider


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider."""
    provider = llm_config.LLM_PROVIDER
    if provider == "openai":
        return OpenAIProvider(
            api_key=llm_config.OPENAI_API_KEY,
            model=llm_config.LLM_MODEL,
            api_base=llm_config.OPENAI_API_BASE,
        )
    if provider == "gemini":
        return GeminiProvider(
            api_key=llm_config.GEMINI_API_KEY,
            model=llm_config.LLM_MODEL,
            api_base=llm_config.GEMINI_API_BASE,
        )
    raise LLMConfigurationError(f"Unsupported LLM_PROVIDER: {provider}")


def is_llm_configured() -> bool:
    """Return True when the configured provider has required credentials."""
    if llm_config.LLM_PROVIDER == "openai":
        return bool(llm_config.OPENAI_API_KEY)
    if llm_config.LLM_PROVIDER == "gemini":
        return bool(llm_config.GEMINI_API_KEY)
    return False
