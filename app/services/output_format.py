"""Output-format routing: template vocabulary vs requested export format."""

from __future__ import annotations

from typing import Any

from app.services.template_format import DOCBOOK_5_BOOK, IEEE_JATS_ARTICLE

OUTPUT_AUTO = "auto"
OUTPUT_IEEE_JATS = "ieee_jats"
OUTPUT_DOCBOOK_5 = "docbook_5"
OUTPUT_EPUB_3 = "epub_3"
OUTPUT_ONIX_3 = "onix_3"

IMPLEMENTED_OUTPUT_FORMATS = frozenset({OUTPUT_IEEE_JATS, OUTPUT_DOCBOOK_5})
REQUESTED_OUTPUT_FORMATS = frozenset(
    {OUTPUT_AUTO, OUTPUT_IEEE_JATS, OUTPUT_DOCBOOK_5, OUTPUT_EPUB_3, OUTPUT_ONIX_3}
)


class OutputFormatError(ValueError):
    """Unsupported or incompatible output-format selection."""


def template_format_from_schema(template_schema: dict[str, Any] | None) -> str:
    if not template_schema:
        return IEEE_JATS_ARTICLE
    explicit = template_schema.get("template_format")
    if explicit:
        return str(explicit)
    root_tag = template_schema.get("root_tag")
    if root_tag == "book":
        return DOCBOOK_5_BOOK
    return IEEE_JATS_ARTICLE


def default_output_for_template(template_format: str) -> str:
    if template_format == DOCBOOK_5_BOOK:
        return OUTPUT_DOCBOOK_5
    return OUTPUT_IEEE_JATS


def resolve_output_format(requested: str, template_schema: dict[str, Any] | None) -> str:
    """Map API ``output_format`` (including ``auto``) to a concrete generator id."""
    normalized = (requested or OUTPUT_AUTO).strip().lower()
    if normalized not in REQUESTED_OUTPUT_FORMATS:
        supported = ", ".join(sorted(REQUESTED_OUTPUT_FORMATS))
        raise OutputFormatError(
            f"Unknown output_format '{requested}'. Supported request values: {supported}."
        )

    template_format = template_format_from_schema(template_schema)

    if normalized == OUTPUT_AUTO:
        return default_output_for_template(template_format)

    if normalized in {OUTPUT_EPUB_3, OUTPUT_ONIX_3}:
        raise OutputFormatError(
            f"Output format '{normalized}' is not implemented yet. "
            f"Supported outputs: {', '.join(sorted(IMPLEMENTED_OUTPUT_FORMATS))}."
        )

    validate_output_format_for_template(normalized, template_format)
    return normalized


def validate_output_format_for_template(output_format: str, template_format: str) -> None:
    if output_format == OUTPUT_IEEE_JATS and template_format == DOCBOOK_5_BOOK:
        raise OutputFormatError(
            "Cannot generate IEEE JATS XML from a DocBook 5.0 <book> template. "
            f"Use output_format='{OUTPUT_DOCBOOK_5}' (or '{OUTPUT_AUTO}') for this template, "
            "or upload an IEEE JATS <article> template for JATS output."
        )
    if output_format == OUTPUT_DOCBOOK_5 and template_format == IEEE_JATS_ARTICLE:
        raise OutputFormatError(
            "Cannot generate DocBook 5.0 book XML from an IEEE JATS <article> template. "
            f"Use output_format='{OUTPUT_IEEE_JATS}' (or '{OUTPUT_AUTO}') for article templates."
        )
