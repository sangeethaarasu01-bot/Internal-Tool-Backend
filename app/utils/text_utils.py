"""Shared text normalization utilities (no layout dependencies)."""

from __future__ import annotations


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip a text string.

    Example::

        >>> normalize_text("  hello\\n  world  ")
        'hello world'
    """
    return " ".join((text or "").replace("\n", " ").split()).strip()
