"""Route XML generation to IEEE JATS or DocBook based on template and request."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.models.semantic_mapping import SemanticMappingBody
from app.services.docbook_generator import DocBookGenerationError, generate_docbook_book_xml
from app.services.docbook_metadata_overlay import DocBookMetadataOverlayResult
from app.services.source_identity import SourceIdentityRecord
from app.services.output_format import (
    OUTPUT_DOCBOOK_5,
    OUTPUT_IEEE_JATS,
    OutputFormatError,
    resolve_output_format,
)
from app.services.template_format import UnsupportedTemplateRootError
from app.services.xml_generator import XmlGenerationError, generate_jats_xml

logger = logging.getLogger(__name__)


def run_jats_xml_transform(
    template_path: str | Path,
    mapping: SemanticMappingBody | dict[str, Any],
) -> str:
    """Run IEEE JATS generation with full exception logging for operations diagnostics."""
    try:
        return generate_jats_xml(template_path, mapping)
    except XmlGenerationError:
        raise
    except UnsupportedTemplateRootError as exc:
        raise XmlGenerationError(str(exc)) from exc
    except MemoryError as exc:
        logger.exception("JATS transform MemoryError for template %s", template_path)
        raise XmlGenerationError(
            "Document too large for JATS transform. Chunk by <chapter> before retrying."
        ) from exc
    except Exception as exc:
        logger.exception("JATS transform failed for template %s", template_path)
        raise XmlGenerationError(f"JATS XML transform failed: {exc}") from exc


def generate_output_xml(
    template_path: str | Path,
    template_schema: dict[str, Any] | None,
    mapping: SemanticMappingBody | dict[str, Any],
    *,
    output_format: str = "auto",
    source: SourceIdentityRecord | None = None,
) -> tuple[str, str, DocBookMetadataOverlayResult | None]:
    """
    Return ``(xml_content, resolved_output_format)``.

    ``mapping`` is used only for IEEE JATS article generation.
    """
    path = Path(template_path)
    resolved = resolve_output_format(
        output_format,
        template_schema,
        template_path=path,
    )

    if resolved == OUTPUT_DOCBOOK_5:
        try:
            xml_content, overlay = generate_docbook_book_xml(path, source=source)
        except DocBookGenerationError as exc:
            raise XmlGenerationError(str(exc)) from exc
        except MemoryError as exc:
            logger.exception("DocBook book XML load failed (MemoryError): %s", path)
            raise XmlGenerationError(
                "Document too large to load as a single book XML. "
                "Use chapter-level DocBook output or reduce template size."
            ) from exc
        return xml_content, resolved, overlay

    if resolved == OUTPUT_IEEE_JATS:
        xml_content = run_jats_xml_transform(path, mapping)
        return xml_content, resolved, None

    raise OutputFormatError(f"No generator registered for output format '{resolved}'.")
