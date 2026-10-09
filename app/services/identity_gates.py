"""Pre/post generation identity validation."""

from __future__ import annotations

import logging
from typing import Any

from lxml import etree

from app.services.docbook_template import extract_docbook_book_metadata
from app.services.output_format import OUTPUT_DOCBOOK_5, OUTPUT_IEEE_JATS
from app.services.source_identity import (
    IdentityConflict,
    IdentityMismatchError,
    SourceIdentityRecord,
    TemplateIdentityRecord,
    build_template_identity,
    compare_source_to_output_metadata,
    compare_source_to_template,
)
from app.services.template_format import DOCBOOK_NS, classify_template_root
from app.utils.xml_helpers import xml_local_name

logger = logging.getLogger(__name__)

IDENTITY_MISMATCH_MESSAGE = "Source PDF and generated content do not match"


def log_processing_stage(
    stage: str,
    *,
    extraction_id: str,
    source_pdf_sha256: str | None = None,
    template_id: str | None = None,
    scope: str | None = None,
    output_format: str | None = None,
    output_storage_key: str | None = None,
    identity_result: str | None = None,
) -> None:
    logger.info(
        "processing_stage=%s extraction_id=%s source_sha256=%s template_id=%s scope=%s "
        "output_format=%s output_key=%s identity_result=%s",
        stage,
        extraction_id,
        (source_pdf_sha256 or "-")[:16],
        template_id or "-",
        scope or "-",
        output_format or "-",
        output_storage_key or "-",
        identity_result or "-",
    )


def _conflict_detail(conflicts: list[IdentityConflict]) -> str:
    parts = [
        f"{c.field} (source={c.source_value!r} vs {c.other_kind}={c.other_value!r})"
        for c in conflicts
    ]
    return "; ".join(parts)


def assert_extraction_context(
    doc: dict[str, Any],
    extraction_id: str,
) -> SourceIdentityRecord:
    doc_id = str(doc.get("_id"))
    if doc_id != extraction_id:
        raise IdentityMismatchError(
            f"Extraction document id mismatch (expected {extraction_id}, got {doc_id})",
            extraction_id=extraction_id,
            conflicts=[
                IdentityConflict(
                    field="extraction_id",
                    source_value=extraction_id,
                    other_value=doc_id,
                    other_kind="storage",
                )
            ],
        )
    return SourceIdentityRecord(
        extraction_id=extraction_id,
        source_pdf_sha256=doc.get("source_pdf_sha256"),
        source_filename=doc.get("original_filename"),
        title=(doc.get("phase1") or {}).get("title"),
        authors=[],
        publisher=None,
        publication_year=None,
        isbn=None,
        doi=None,
        page_count=doc.get("page_count"),
        publication_document_type=None,
    )


def verify_pre_generation_identity(
    *,
    extraction_id: str,
    source: SourceIdentityRecord,
    template: dict[str, Any],
    template_path: str,
    output_format: str,
) -> None:
    """Abort when the uploaded template clearly belongs to a different work than the PDF."""
    if output_format not in {OUTPUT_DOCBOOK_5, OUTPUT_IEEE_JATS}:
        return

    template_identity = build_template_identity(template, template_path)
    if output_format == OUTPUT_DOCBOOK_5:
        if not source.title and not source.isbn:
            logger.warning(
                "identity_gate_skip extraction_id=%s reason=weak_source_metadata",
                extraction_id,
            )
            return
        conflicts = compare_source_to_template(source, template_identity)
        if conflicts:
            log_processing_stage(
                "pre_generation_identity_reject",
                extraction_id=extraction_id,
                source_pdf_sha256=source.source_pdf_sha256,
                template_id=template_identity.template_id,
                output_format=output_format,
                identity_result=_conflict_detail(conflicts),
            )
            raise IdentityMismatchError(
                f"{IDENTITY_MISMATCH_MESSAGE} (job {extraction_id}): {_conflict_detail(conflicts)}",
                extraction_id=extraction_id,
                conflicts=conflicts,
            )
    log_processing_stage(
        "pre_generation_identity_ok",
        extraction_id=extraction_id,
        source_pdf_sha256=source.source_pdf_sha256,
        template_id=template_identity.template_id,
        output_format=output_format,
        identity_result="ok",
    )


def _parse_docbook_output_identity(xml_content: str) -> dict[str, Any]:
    root = etree.fromstring(xml_content.encode("utf-8"))
    info = classify_template_root(root)
    if info.template_format != "docbook_5_book":
        raise ValueError("Output is not a DocBook book root")
    meta = extract_docbook_book_metadata(root)
    return {
        "title": meta.title,
        "isbns": [ident.value for ident in meta.isbns if ident.value],
        "doi": meta.doi,
        "publisher": meta.publisher,
        "publication_year": meta.copyright_year,
        "root_tag": xml_local_name(root),
    }


def _parse_jats_output_identity(xml_content: str) -> dict[str, Any]:
    root = etree.fromstring(xml_content.encode("utf-8"))
    if xml_local_name(root) != "article":
        raise ValueError("Output is not a JATS article root")
    title = None
    article_meta = root.find(".//article-meta")
    if article_meta is not None:
        title_el = article_meta.find(".//article-title")
        if title_el is not None:
            title = " ".join(title_el.itertext()).strip() or None
    return {
        "title": title,
        "isbns": [],
        "doi": None,
        "publisher": None,
        "publication_year": None,
        "root_tag": "article",
    }


def verify_post_generation_identity(
    *,
    extraction_id: str,
    source: SourceIdentityRecord,
    xml_content: str,
    output_format: str,
    expected_root: str,
) -> None:
    if output_format == OUTPUT_DOCBOOK_5:
        parsed = _parse_docbook_output_identity(xml_content)
    elif output_format == OUTPUT_IEEE_JATS:
        parsed = _parse_jats_output_identity(xml_content)
    else:
        return

    if parsed.get("root_tag") != expected_root:
        conflicts = [
            IdentityConflict(
                field="root_element",
                source_value=expected_root,
                other_value=str(parsed.get("root_tag")),
                other_kind="output",
            )
        ]
        raise IdentityMismatchError(
            f"{IDENTITY_MISMATCH_MESSAGE} (job {extraction_id}): root element mismatch",
            extraction_id=extraction_id,
            conflicts=conflicts,
        )

    conflicts = compare_source_to_output_metadata(
        source,
        title=parsed.get("title"),
        isbns=list(parsed.get("isbns") or []),
        doi=parsed.get("doi"),
        publisher=parsed.get("publisher"),
        publication_year=parsed.get("publication_year"),
    )
    if conflicts:
        log_processing_stage(
            "post_generation_identity_reject",
            extraction_id=extraction_id,
            source_pdf_sha256=source.source_pdf_sha256,
            output_format=output_format,
            identity_result=_conflict_detail(conflicts),
        )
        raise IdentityMismatchError(
            f"{IDENTITY_MISMATCH_MESSAGE} (job {extraction_id}): {_conflict_detail(conflicts)}",
            extraction_id=extraction_id,
            conflicts=conflicts,
        )
    log_processing_stage(
        "post_generation_identity_ok",
        extraction_id=extraction_id,
        source_pdf_sha256=source.source_pdf_sha256,
        output_format=output_format,
        identity_result="ok",
    )
