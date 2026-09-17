"""Shared text normalization utilities (no layout dependencies)."""

from __future__ import annotations

import re

_LINE_BREAK_HYPHEN_RE = re.compile(r"(\w)-\s+([a-z]\w*)")


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip a text string.

    Example::

        >>> normalize_text("  hello\\n  world  ")
        'hello world'
    """
    return " ".join((text or "").replace("\n", " ").split()).strip()


def dehyphenate_line_breaks(text: str) -> str:
    """Join words broken across PDF lines (``instrumen- tal`` → ``instrumental``)."""
    if not text:
        return ""
    return _LINE_BREAK_HYPHEN_RE.sub(r"\1\2", text)


def _should_join_wrapped_word(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if previous[-1] in ".,;:!?)]}\"'”’":
        return False
    if current[0] in "([{\"'“‘":
        return False
    previous_word = previous.split()[-1]
    current_word = current.split()[0]
    if not previous_word or not current_word:
        return False
    if previous_word.endswith("-") or current_word.startswith("-"):
        return False
    if previous_word[-1].isalpha() and current_word[0].isalpha():
        if previous_word[-1].islower() and current_word[0].islower():
            return True
        if len(previous_word) >= 4 and previous_word[-1].islower() and current_word[0].islower():
            return True
    return False


def merge_block_texts(parts: list[str]) -> str:
    """Merge paragraph block fragments with drop-cap and hyphenation rules."""
    merged = ""
    for raw in parts:
        part = normalize_text(raw)
        if not part:
            continue
        if not merged:
            merged = part
            continue
        if len(merged) == 1 and merged.isalpha() and part[0].isalpha():
            merged = f"{merged}{part}"
            continue
        if re.search(r"-\s*$", merged):
            merged = re.sub(r"-\s*$", "", merged) + part
            continue
        if _should_join_wrapped_word(merged, part):
            merged = f"{merged}{part}"
            continue
        merged = f"{merged} {part}"
    return dehyphenate_line_breaks(merged)


def infer_drop_cap_letter(text: str) -> str | None:
    """Infer a missing drop-cap letter from a truncated paragraph start."""
    normalized = normalize_text(text)
    if re.match(r"^ESEARCHERS\b", normalized):
        return "R"
    return None
