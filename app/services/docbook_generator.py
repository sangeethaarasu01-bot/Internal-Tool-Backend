"""DocBook 5.0 book output (template-preserving export path)."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.services.docbook_metadata_overlay import (
    DocBookMetadataOverlayResult,
    apply_pdf_metadata_to_docbook_book,
)
from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS, classify_template_root
from app.utils.xml_serializer import serialize_lxml_tree


class DocBookGenerationError(ValueError):
    """DocBook book XML could not be produced."""


def generate_docbook_book_xml(
    template_path: str | Path,
    *,
    source: SourceIdentityRecord | None = None,
) -> tuple[str, DocBookMetadataOverlayResult]:
    """
    Produce DocBook 5.0 book XML from the uploaded template skeleton.

    Preserves template structure and chapter bodies; when ``source`` is provided,
    book-level ``<info>`` publication fields are taken from the current PDF extraction.
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

    overlay = DocBookMetadataOverlayResult()
    if source is not None:
        overlay = apply_pdf_metadata_to_docbook_book(root, source)

    xml = serialize_lxml_tree(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=tree.docinfo.doctype if tree.docinfo.doctype else None,
    )
    return xml, overlay
