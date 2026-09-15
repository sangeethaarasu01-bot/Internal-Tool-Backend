"""Sanitize and escape text for XML 1.0 element and attribute content."""

from __future__ import annotations

import html
import re

# XML 1.0 forbids NULL and most C0 controls (tab, LF, CR are allowed).
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFE\uFFFF]")


def sanitize_xml_text(value: str | None) -> str:
    """Remove characters that are illegal in XML 1.0 text nodes."""
    if not value:
        return ""
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.replace("\x00", "")
    cleaned = _ILLEGAL_XML_CHARS.sub("", cleaned)
    return cleaned.encode("utf-8", "ignore").decode("utf-8")


def escape_xml_text(value: str | None) -> str:
    """Sanitize then escape text for safe inclusion in tagged XML output."""
    return html.escape(sanitize_xml_text(value), quote=True)
