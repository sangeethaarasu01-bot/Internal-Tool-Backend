"""Sanitize text for XML DOM construction (not final serialization escaping)."""

from __future__ import annotations

import logging
import re
from typing import Any

from lxml import etree
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

# XML 1.0 Char: tab, LF, CR, and valid Unicode ranges; exclude NULL and other C0 controls.
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFE\uFFFF]")
_PREVIEW_LEN = 40

# Used only at final serialization (xml_serializer); exported for shared normalization.
_TYPOGRAPHIC_QUOTE_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u2035": "'",
        "\u2039": "'",
        "\u203a": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u2036": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\uff07": "'",
        "\uff02": '"',
    }
)


def find_invalid_xml_char_codes(value: str) -> list[int]:
    """Return distinct code points that are illegal in XML 1.0 text content."""
    codes: list[int] = []
    for char in value:
        if char in "\t\n\r":
            continue
        code = ord(char)
        if _is_xml_legal_char(code):
            continue
        if code not in codes:
            codes.append(code)
    return codes


def _is_xml_legal_char(code: int) -> bool:
    return (
        code == 0x9
        or code == 0xA
        or code == 0xD
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def _preview_text(value: str) -> str:
    preview = value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    if len(preview) > _PREVIEW_LEN:
        return preview[: _PREVIEW_LEN - 3] + "..."
    return preview


def _log_removed_chars(original: str, cleaned: str, log_context: dict[str, Any] | None) -> None:
    if original == cleaned:
        return
    invalid_codes = find_invalid_xml_char_codes(original)
    if not invalid_codes:
        return
    context = log_context or {}
    code_repr = ", ".join(f"U+{code:04X}" for code in invalid_codes[:5])
    logger.warning(
        "Invalid XML character(s) removed: %s | semantic_type=%s source=%s field=%s preview=%r",
        code_repr,
        context.get("semantic_type", "-"),
        context.get("source", "-"),
        context.get("field", "-"),
        _preview_text(original),
    )


def normalize_typographic_quotes(value: str) -> str:
    """Map PDF smart quotes to ASCII straight quotes (serialization boundary helper)."""
    return value.translate(_TYPOGRAPHIC_QUOTE_MAP)


def sanitize_xml_text(value: str | None, *, log_context: dict[str, Any] | None = None) -> str:
    """Remove characters that are illegal in XML 1.0 text nodes."""
    if not value:
        return ""
    if not isinstance(value, str):
        value = str(value)
    cleaned = _ILLEGAL_XML_CHARS.sub("", value)
    _log_removed_chars(value, cleaned, log_context)
    return cleaned


def escape_xml_text(value: str | None, *, log_context: dict[str, Any] | None = None) -> str:
    """Escape ``&``, ``<``, ``>`` for intermediate tagged output (not final quote entities)."""
    cleaned = sanitize_xml_text(value, log_context=log_context)
    return escape(cleaned)


def escape_xml_attribute(value: str | None, *, log_context: dict[str, Any] | None = None) -> str:
    """Escape attribute values for intermediate tagged output (not final quote entities)."""
    cleaned = sanitize_xml_text(value, log_context=log_context)
    return escape(cleaned).replace('"', "&quot;")


def set_lxml_text(
    element: etree._Element,
    value: str | None,
    *,
    tail: bool = False,
    log_context: dict[str, Any] | None = None,
) -> None:
    """Assign sanitized text to an lxml element ``text`` or ``tail`` field."""
    cleaned = sanitize_xml_text(value, log_context=log_context)
    if tail:
        element.tail = cleaned
    else:
        element.text = cleaned


def normalize_person_name_text(value: str | None) -> str:
    """Collapse and trim whitespace in JATS ``given-names`` / ``surname`` fields."""
    if not value:
        return ""
    cleaned = sanitize_xml_text(value)
    return " ".join(cleaned.split())


def set_lxml_attr(
    element: etree._Element,
    name: str,
    value: str | None,
    *,
    log_context: dict[str, Any] | None = None,
) -> None:
    """Assign a sanitized attribute value to an lxml element."""
    element.set(name, sanitize_xml_text(value, log_context=log_context))
