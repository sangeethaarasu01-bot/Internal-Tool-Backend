"""Loguru configuration."""

import sys
from pathlib import Path

from loguru import logger

from app.config import settings

_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(
    sys.stdout,
    level=settings.LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
)
logger.add(
    _LOG_DIR / "app.log",
    rotation="10 MB",
    retention="7 days",
    level=settings.LOG_LEVEL,
)

__all__ = ["logger"]
