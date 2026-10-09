"""Route XML generation to IEEE JATS or DocBook based on template and request."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.semantic_mapping import SemanticMappingBody
from app.services.docbook_generator import DocBookGenerationError, generate_docbook_book_xml
from app.services.output_format import (
    OUTPUT_DOCBOOK_5,
    OUTPUT_IEEE_JATS,
    OutputFormatError,
    resolve_output_format,
)
from app.services.xml_generator import XmlGenerationError, generate_jats_xml


def generate_output_xml(
    template_path: str | Path,
    template_schema: dict[str, Any] | None,
    mapping: SemanticMappingBody | dict[str, Any],
    *,
    output_format: str = "auto",
) -> tuple[str, str]:
    """
    Return ``(xml_content, resolved_output_format)``.

    ``mapping`` is used only for IEEE JATS article generation.
    """
    resolved = resolve_output_format(output_format, template_schema)
    path = Path(template_path)

    if resolved == OUTPUT_DOCBOOK_5:
        try:
            xml_content = generate_docbook_book_xml(path)
        except DocBookGenerationError as exc:
            raise XmlGenerationError(str(exc)) from exc
        return xml_content, resolved

    if resolved == OUTPUT_IEEE_JATS:
        xml_content = generate_jats_xml(path, mapping)
        return xml_content, resolved

    raise OutputFormatError(f"No generator registered for output format '{resolved}'.")
