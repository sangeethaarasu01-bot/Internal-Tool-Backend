"""Remove foreign-book skeleton content from DocBook templates after PDF overlay."""

from __future__ import annotations

import re

from lxml import etree

from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS
from app.utils.isbn_selection import isbn13_digits
from app.utils.xml_helpers import iter_element_children, xml_local_name

_PDF_ASSET_ISBN_RE = re.compile(r"pdfs/(\d{10,13})", re.IGNORECASE)
_TEMPLATE_BODY_LOCAL_NAMES = frozenset(
    {
        "part",
        "chapter",
        "appendix",
        "preface",
        "introduction",
        "colophon",
        "dedication",
        "toc",
        "acknowledgements",
        "bibliography",
        "index",
        "glossary",
    }
)
_REMOVABLE_ANCESTOR_NAMES = frozenset(
    {
        "cover",
        "preface",
        "dedication",
        "toc",
        "colophon",
        "part",
        "chapter",
        "mediaobject",
        "imageobject",
    }
)


def _source_isbn_digit_keys(source: SourceIdentityRecord) -> set[str]:
    keys: set[str] = set()
    for raw in [source.isbn, *(source.isbns or [])]:
        if not raw:
            continue
        digits = isbn13_digits(raw) or re.sub(r"[^0-9]", "", str(raw))
        if len(digits) >= 10:
            keys.add(digits)
    return keys


def strip_template_narrative_shell(book: etree._Element) -> int:
    """Drop all template body nodes under ``<book>`` except ``<info>`` (PDF supplies narrative)."""
    removed = 0
    for child in list(iter_element_children(book)):
        if xml_local_name(child) == "info":
            continue
        if xml_local_name(child) in _TEMPLATE_BODY_LOCAL_NAMES:
            book.remove(child)
            removed += 1
    return removed


def _remove_subtree_root(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _fileref_matches_foreign_pdf_asset(fileref: str, allowed_isbns: set[str]) -> bool:
    if not fileref or "pdfs/" not in fileref.lower():
        return False
    if not allowed_isbns:
        return False
    match = _PDF_ASSET_ISBN_RE.search(fileref)
    if not match:
        return False
    asset_key = match.group(1)
    for allowed in allowed_isbns:
        if asset_key == allowed or asset_key in allowed or allowed in asset_key:
            return False
    return True


def strip_foreign_pdf_asset_subtrees(
    book: etree._Element,
    source: SourceIdentityRecord,
) -> int:
    """Remove preface/toc/cover blocks whose ``fileref`` uses another book's PDF prefix."""
    allowed = _source_isbn_digit_keys(source)
    if not allowed:
        return 0
    removed = 0
    for imagedata in list(book.iter(f"{{{DOCBOOK_NS}}}imagedata")):
        fileref = (imagedata.get("fileref") or "").strip()
        if not _fileref_matches_foreign_pdf_asset(fileref, allowed):
            continue
        node: etree._Element | None = imagedata
        while node is not None:
            name = xml_local_name(node)
            if name == "book":
                break
            if name in _REMOVABLE_ANCESTOR_NAMES:
                _remove_subtree_root(node)
                removed += 1
                break
            node = node.getparent()
    return removed


def sanitize_docbook_template_after_pdf_overlay(
    book: etree._Element,
    source: SourceIdentityRecord,
) -> dict[str, int]:
    """Ensure only PDF identity remains in the template shell (not a prior sample book)."""
    from app.services.docbook_metadata_overlay import _strip_template_marketing_from_info

    stats = {"narrative_shell": 0, "foreign_assets": 0, "info_marketing": 0}
    info = next(
        (child for child in iter_element_children(book) if xml_local_name(child) == "info"),
        None,
    )
    if info is not None:
        before = len(list(info))
        _strip_template_marketing_from_info(info)
        stats["info_marketing"] = max(0, before - len(list(info)))
    stats["narrative_shell"] = strip_template_narrative_shell(book)
    stats["foreign_assets"] = strip_foreign_pdf_asset_subtrees(book, source)
    return stats
