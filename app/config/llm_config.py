"""LLM provider configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROMPTS_DIR = ROOT / "prompts"

SEMANTIC_MAPPING_PROMPT_VERSION = "v1"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
GEMINI_API_BASE = os.getenv(
    "GEMINI_API_BASE",
    "https://generativelanguage.googleapis.com/v1beta",
).strip().rstrip("/")
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
GEMINI_REQUEST_TIMEOUT = float(os.getenv("GEMINI_REQUEST_TIMEOUT", "300"))


def _resolve_llm_provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if GEMINI_API_KEY:
        return "gemini"
    return "openai"


def _resolve_llm_model(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", os.getenv("LLM_MODEL", "gemini-2.0-flash")).strip()
    return os.getenv("LLM_MODEL", "gpt-4o").strip()


def _resolve_llm_max_retries(provider: str) -> int:
    explicit = os.getenv("LLM_MAX_RETRIES", "").strip()
    if explicit:
        return max(1, min(int(explicit), 5))
    # Gemini large payloads often time out; avoid doubling wait with a second attempt.
    return 1 if provider == "gemini" else 2


LLM_PROVIDER = _resolve_llm_provider()
LLM_MODEL = _resolve_llm_model(LLM_PROVIDER)
LLM_MAX_RETRIES = _resolve_llm_max_retries(LLM_PROVIDER)


def semantic_mapping_prompt_path(version: str = SEMANTIC_MAPPING_PROMPT_VERSION) -> Path:
    return PROMPTS_DIR / version / "semantic_mapping_system.txt"


def load_semantic_mapping_system_prompt(version: str = SEMANTIC_MAPPING_PROMPT_VERSION) -> str:
    path = semantic_mapping_prompt_path(version)
    if not path.exists():
        raise FileNotFoundError(f"Semantic mapping prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()
