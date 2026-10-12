"""Split display author names into JATS given-names and surname."""

from __future__ import annotations

import re

_PARTICLE_PREFIXES = frozenset(
    {"van", "von", "de", "der", "den", "la", "le", "del", "da", "di", "st", "st."}
)


def split_person_name(display_name: str) -> tuple[str, str]:
    """Return ``(given_names, surname)`` from a Western-order author string."""
    cleaned = re.sub(r"\s+", " ", (display_name or "").strip())
    if not cleaned:
        return "", ""
    tokens = cleaned.split()
    if len(tokens) == 1:
        return "", tokens[0]
    surname_tokens = [tokens[-1]]
    index = len(tokens) - 2
    while index >= 1 and tokens[index].lower().rstrip(".") in _PARTICLE_PREFIXES:
        surname_tokens.insert(0, tokens[index])
        index -= 1
    given = " ".join(tokens[: index + 1])
    surname = " ".join(surname_tokens)
    return given, surname
