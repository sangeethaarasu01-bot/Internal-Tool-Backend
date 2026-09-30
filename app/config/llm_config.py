"""LLM provider configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROMPTS_DIR = ROOT / "prompts"

SEMANTIC_MAPPING_PROMPT_VERSION = "v1"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_API_BASE = os.getenv(
    "GEMINI_API_BASE",
    "https://generativelanguage.googleapis.com/v1beta",
).strip().rstrip("/")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
ANTHROPIC_API_BASE = os.getenv(
    "ANTHROPIC_API_BASE",
    "https://api.anthropic.com/v1",
).strip().rstrip("/")
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
ANTHROPIC_REQUEST_TIMEOUT = float(
    os.getenv("ANTHROPIC_REQUEST_TIMEOUT", os.getenv("CLAUDE_REQUEST_TIMEOUT", "300"))
)


def _resolve_llm_provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit in ("google", "gemini"):
        return "gemini"
    if explicit:
        return explicit
    if GEMINI_API_KEY and not ANTHROPIC_API_KEY and not OPENAI_API_KEY:
        return "gemini"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    return "openai"


def _resolve_llm_model(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", os.getenv("LLM_MODEL", "gemini-2.5-flash")).strip()
    if provider == "anthropic":
        return os.getenv(
            "CLAUDE_MODEL",
            os.getenv("LLM_MODEL", "claude-sonnet-4-20250514"),
        ).strip()
    return os.getenv("LLM_MODEL", "gpt-4o").strip()


def _resolve_llm_max_retries(provider: str) -> int:
    explicit = os.getenv("LLM_MAX_RETRIES", "").strip()
    if explicit:
        return max(1, min(int(explicit), 5))
    # Large semantic-mapping payloads can time out; avoid doubling wait with a second attempt.
    if provider in ("anthropic", "gemini"):
        return 1
    return 2


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
