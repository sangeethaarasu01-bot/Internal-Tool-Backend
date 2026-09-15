"""LLM provider configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROMPTS_DIR = ROOT / "prompts"

SEMANTIC_MAPPING_PROMPT_VERSION = "v1"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
LLM_MAX_RETRIES = max(1, min(int(os.getenv("LLM_MAX_RETRIES", "2")), 5))
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))


def semantic_mapping_prompt_path(version: str = SEMANTIC_MAPPING_PROMPT_VERSION) -> Path:
    return PROMPTS_DIR / version / "semantic_mapping_system.txt"


def load_semantic_mapping_system_prompt(version: str = SEMANTIC_MAPPING_PROMPT_VERSION) -> str:
    path = semantic_mapping_prompt_path(version)
    if not path.exists():
        raise FileNotFoundError(f"Semantic mapping prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()
