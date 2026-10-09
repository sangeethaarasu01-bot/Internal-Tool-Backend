"""DocBook 5.0 book output (template-preserving export path)."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.services.template_format import DOCBOOK_NS, classify_template_root
from app.utils.xml_serializer import serialize_lxml_tree


class DocBookGenerationError(ValueError):
    """DocBook book XML could not be produced."""


def generate_docbook_book_xml(template_path: str | Path) -> str:
    """
    Produce DocBook 5.0 book XML from the uploaded template skeleton.

    Preserves the template hierarchy, namespaces, and content (lossless round-trip
    of the template file). PDF-to-chapter content merge is not applied on this path.
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

    return serialize_lxml_tree(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=tree.docinfo.doctype if tree.docinfo.doctype else None,
    )
