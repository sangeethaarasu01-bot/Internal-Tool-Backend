"""Collapse accidental duplicated title phrases (e.g. PDF block repeated twice)."""

from __future__ import annotations

import re


def collapse_repeated_title_phrase(text: str) -> str:
    """
    If text is two identical phrases in a row (``X X``), return ``X`` only.
    """
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return ""
    parts = normalized.split(" ")
    for split_index in range(1, len(parts)):
        left = " ".join(parts[:split_index])
        right = " ".join(parts[split_index:])
        if left and left == right:
            return left
    return normalized
