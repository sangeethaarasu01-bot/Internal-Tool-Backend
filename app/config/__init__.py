"""Application configuration via pydantic-settings."""

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_light_pdf_extract() -> bool:
    """Render.com sets RENDER=true; free tier needs lighter PDF processing."""
    if os.getenv("LIGHT_PDF_EXTRACT", "").lower() in ("true", "1", "yes"):
        return True
    return os.getenv("RENDER", "").lower() in ("true", "1", "yes")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    LLM_PROVIDER: Literal["openai", "anthropic", "gemini"] = "anthropic"
    LLM_MODEL_GENERATION: str = "claude-sonnet-4-20250514"
    LLM_MODEL_MATCHING: str = "claude-3-5-haiku-20241022"
    LLM_MODEL_EXTRACTION: str = "claude-3-5-haiku-20241022"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    MAX_RETRIES: int = 3
    DATA_DIR: Path = Path("./data")
    DB_URL: str = "sqlite:///./jobs.db"
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://internal-tool-sepia.vercel.app",
    ]
    # Vercel preview deployments (e.g. internal-tool-sepia-git-xxx.vercel.app)
    CORS_ORIGIN_REGEX: str = r"https://.*\.vercel\.app"
    SCHEMA_CACHE_TTL_DAYS: int = 30
    MAX_PDF_PAGES: int = 40
    LOG_LEVEL: str = "INFO"
    # Skip heavy pdfplumber tables + figure pixmap export (required on Render 512MB)
    LIGHT_PDF_EXTRACT: bool = _default_light_pdf_extract()
    # Layout pipeline is accurate but CPU-heavy; disable on small Render instances if needed
    USE_LAYOUT_PDF_EXTRACT: bool = os.getenv("USE_LAYOUT_PDF_EXTRACT", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # When true, billing/auth/rate-limit errors use deterministic offline LLM mocks
    LLM_FALLBACK_MOCK: bool = True

    @property
    def uploads_dir(self) -> Path:
        return self.DATA_DIR / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.DATA_DIR / "outputs"

    @property
    def schemas_dir(self) -> Path:
        return self.DATA_DIR / "schemas"

    def ensure_data_dirs(self) -> None:
        for d in (self.uploads_dir, self.outputs_dir, self.schemas_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_llm_model(self, role: str) -> str:
        """Return model id for generation / matching / extraction (Gemini-aware)."""
        by_role = {
            "generation": self.LLM_MODEL_GENERATION,
            "matching": self.LLM_MODEL_MATCHING,
            "extraction": self.LLM_MODEL_EXTRACTION,
        }
        model = by_role.get(role.lower(), self.LLM_MODEL_GENERATION)
        if self.LLM_PROVIDER == "gemini":
            name = model.strip()
            if not (name.startswith("gemini") or name.startswith("models/")):
                return self.GEMINI_MODEL
        return model


settings = Settings()
settings.ensure_data_dirs()
