"""Select a primary ISBN from PDF/source metadata for DocBook identity."""

from __future__ import annotations

import re
from typing import Iterable

ISBN_DIGITS_RE = re.compile(r"[^0-9Xx]")

ISBN_WITH_QUAL_RE = re.compile(
    r"ISBN(?:-1[03])?:?\s*([\d\-Xx]{10,17})\s*(?:\(([^)]+)\))?",
    re.IGNORECASE,
)

_PRINT_QUALIFIER_MARKERS = (
    "cloth",
    "hardcover",
    "hardback",
    "alk. paper",
    "alk paper",
    "print",
)


def extract_isbn_entries(text: str) -> list[tuple[str, str | None]]:
    """Return ISBN values in source order with optional parenthetical qualifiers."""
    seen: set[str] = set()
    entries: list[tuple[str, str | None]] = []
    for match in ISBN_WITH_QUAL_RE.finditer(text or ""):
        value = match.group(1).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        qualifier = (match.group(2) or "").strip() or None
        entries.append((value, qualifier))
    return entries


def _is_print_qualifier(qualifier: str | None) -> bool:
    if not qualifier:
        return False
    lowered = qualifier.lower()
    return any(marker in lowered for marker in _PRINT_QUALIFIER_MARKERS)


def role_from_isbn_qualifier(qualifier: str | None) -> str | None:
    """Map source parenthetical text to biblioid role when explicit."""
    if not qualifier:
        return None
    lowered = qualifier.lower()
    if _is_print_qualifier(lowered):
        return "hardback"
    if "electronic" in lowered or "ebook" in lowered or "e-book" in lowered:
        return "electronic"
    return None


def normalize_isbn_biblioid_role(role: str | None) -> str | None:
    """DocBook output uses ``hardback`` for print/cloth ISBNs."""
    cleaned = (role or "").strip().lower()
    if not cleaned:
        return None
    if cleaned in {"cloth", "hardcover", "hardback", "print"}:
        return "hardback"
    if cleaned == "electronic":
        return "electronic"
    return cleaned


def _normalize_isbn_digits(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = ISBN_DIGITS_RE.sub("", value.strip())
    if len(cleaned) < 10:
        return None
    if len(cleaned) == 13:
        return cleaned
    if len(cleaned) == 10:
        return cleaned
    return cleaned[-13:] if len(cleaned) > 13 else cleaned


def isbn13_digits(isbn: str | None) -> str | None:
    """Return 13-digit ISBN for xml:id, or None if not available."""
    digits = _normalize_isbn_digits(isbn)
    if not digits:
        return None
    if len(digits) == 13:
        return digits
    return None


def book_root_xml_id(isbn: str | None) -> str | None:
    """``b-`` + ISBN-13 without hyphens."""
    digits = isbn13_digits(isbn)
    return f"b-{digits}" if digits else None


def select_primary_isbn(entries: Iterable[tuple[str, str | None]]) -> str | None:
    """
    Prefer print/cloth ISBN; else first ISBN-13 in source order; else first entry.
    """
    ordered = list(entries)
    if not ordered:
        return None
    for value, qualifier in ordered:
        if _is_print_qualifier(qualifier):
            return value
    for value, _qualifier in ordered:
        if isbn13_digits(value):
            return value
    return ordered[0][0]


def select_primary_isbn_from_lists(
    isbns: list[str] | None,
    *,
    fallback: str | None = None,
    qualifiers: dict[str, str] | None = None,
) -> str | None:
    """Build entries from parallel lists when qualifiers are keyed by ISBN string."""
    qual_map = qualifiers or {}
    entries: list[tuple[str, str | None]] = []
    for value in isbns or []:
        cleaned = (value or "").strip()
        if cleaned:
            entries.append((cleaned, qual_map.get(cleaned)))
    if not entries and fallback:
        entries.append((fallback.strip(), qual_map.get(fallback.strip())))
    return select_primary_isbn(entries)
