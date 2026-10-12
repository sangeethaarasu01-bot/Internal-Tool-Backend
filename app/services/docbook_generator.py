"""DocBook 5.0 book output (template-preserving export path)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from lxml import etree

logger = logging.getLogger(__name__)

from app.models.semantic_mapping import SemanticMappingBody
from app.services.docbook_body_merge import (
    DocBookBodyMergeResult,
    apply_pdf_body_to_docbook_book,
)
from app.services.docbook_metadata_overlay import (
    DocBookMetadataOverlayResult,
    apply_pdf_metadata_to_docbook_book,
)
from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS, classify_template_root
from app.services.docbook_structure_fixup import normalize_docbook_book_structure
from app.services.docbook_toc_front_matter import insert_book_toc_front_matter
from app.services.docbook_template_sanitizer import sanitize_docbook_template_after_pdf_overlay
from app.utils.docbook_processing_instructions import (
    restore_processing_instructions,
    snapshot_processing_instructions,
)
from app.utils.docbook_xml_ids import normalize_docbook_book_xml_language
from app.utils.xml_serializer import serialize_lxml_tree


class DocBookGenerationError(ValueError):
    """DocBook book XML could not be produced."""


@dataclass
class DocBookGenerationResult:
    metadata: DocBookMetadataOverlayResult
    body: DocBookBodyMergeResult


def generate_docbook_book_xml(
    template_path: str | Path,
    *,
    source: SourceIdentityRecord | None = None,
    mapping: SemanticMappingBody | dict | None = None,
    ir: dict | None = None,
) -> tuple[str, DocBookGenerationResult]:
    """
    Produce DocBook 5.0 book XML from the uploaded template skeleton.

    Book-level ``<info>`` comes from the PDF when ``source`` is set. Chapter and
    part narrative is rebuilt from ``mapping`` / ``ir`` when the PDF body is present.
    """
    path = Path(template_path)
    if not path.is_file():
        raise DocBookGenerationError(f"Template XML not found: {path}")

    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        raise DocBookGenerationError(f"Invalid DocBook template XML: {exc}") from exc

    root = tree.getroot()
    info = classify_template_root(root)
    if info.template_format != "docbook_5_book":
        raise DocBookGenerationError("Template is not a DocBook 5.0 <book> document.")

    if info.namespace_uri != DOCBOOK_NS:
        raise DocBookGenerationError(
            f"DocBook book root must use namespace {DOCBOOK_NS!r}."
        )

    pi_snapshot = snapshot_processing_instructions(root)

    overlay = DocBookMetadataOverlayResult()
    if source is not None:
        overlay = apply_pdf_metadata_to_docbook_book(root, source)
        sanitizer_stats = sanitize_docbook_template_after_pdf_overlay(root, source)
        if any(sanitizer_stats.values()):
            logger.info("docbook_template_sanitizer %s", sanitizer_stats)

    body_merge = apply_pdf_body_to_docbook_book(root, mapping, ir=ir)
    if body_merge.warnings:
        overlay.warnings.extend(body_merge.warnings)

    if source is not None and source.toc_entries:
        insert_book_toc_front_matter(root, list(source.toc_entries))

    normalize_docbook_book_structure(root)
    normalize_docbook_book_xml_language(root)
    restored = restore_processing_instructions(root, pi_snapshot)
    if restored:
        logger.info("docbook restored %s template processing instructions", restored)

    xml = serialize_lxml_tree(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=tree.docinfo.doctype if tree.docinfo.doctype else None,
        text_escape_mode="docbook",
    )
    return xml, DocBookGenerationResult(metadata=overlay, body=body_merge)
