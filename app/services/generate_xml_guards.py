"""Pre-flight checks for POST /generate-xml (routing, size, JATS root)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.models.semantic_mapping import SemanticMappingBody
from app.services.template_format import (
    DOCBOOK_5_BOOK,
    IEEE_JATS_ARTICLE,
    TemplateRootInfo,
    UnsupportedTemplateRootError,
    classify_template_root,
)
OUTPUT_IEEE_JATS = "ieee_jats"

JATS_REQUIRES_ARTICLE_DETAIL = (
    "IEEE JATS requires <article>; got <{root}>. "
    "Convert to per-chapter articles or choose a book-compatible output."
)

JATS_DOCUMENT_TOO_LARGE_DETAIL = (
    "Document too large for JATS transform. Chunk by <chapter> before retrying."
)


class JatsArticleRequiredError(ValueError):
    """Template root is not an IEEE JATS <article>."""


class JatsTransformTooLargeError(ValueError):
    """Semantic mapping + template exceed the JATS transform size budget."""


def jats_requires_article_detail(root_local_name: str) -> str:
    return JATS_REQUIRES_ARTICLE_DETAIL.format(root=root_local_name)


def classify_template_path(template_path: str | Path) -> TemplateRootInfo:
    path = Path(template_path)
    if not path.is_file():
        raise FileNotFoundError(f"Template XML not found: {path}")
    from lxml import etree

    root = etree.parse(str(path)).getroot()
    return classify_template_root(root)


def effective_template_format(
    template_schema: dict[str, Any] | None,
    template_path: str | Path,
) -> str:
    """
    Prefer the on-disk template root over a stale or empty stored schema.

    Fixes mis-routing when Mongo ``template_schema`` lacks ``template_format`` but
    the uploaded file is a DocBook ``<book>``.
    """
    file_info = classify_template_path(template_path)
    schema_format = None
    if template_schema:
        explicit = template_schema.get("template_format")
        if explicit:
            schema_format = str(explicit)
        elif template_schema.get("root_tag") == "book":
            schema_format = DOCBOOK_5_BOOK
        elif template_schema.get("root_tag") == "article":
            schema_format = IEEE_JATS_ARTICLE

    if schema_format in {DOCBOOK_5_BOOK, IEEE_JATS_ARTICLE}:
        if (
            schema_format == IEEE_JATS_ARTICLE
            and file_info.template_format == DOCBOOK_5_BOOK
        ):
            return DOCBOOK_5_BOOK
        if (
            schema_format == DOCBOOK_5_BOOK
            and file_info.template_format == IEEE_JATS_ARTICLE
        ):
            return IEEE_JATS_ARTICLE
        return schema_format
    return file_info.template_format


def assert_jats_article_template_root(template_path: str | Path) -> TemplateRootInfo:
    info = classify_template_path(template_path)
    local = info.local_name
    if info.template_format != IEEE_JATS_ARTICLE:
        raise JatsArticleRequiredError(jats_requires_article_detail(local))
    return info


def jats_max_transform_bytes() -> int:
    raw = os.getenv("JATS_MAX_TRANSFORM_BYTES", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    try:
        from app.config import settings

        return int(settings.MONGODB_MAX_PAYLOAD_BYTES)
    except Exception:
        return 14 * 1024 * 1024


def estimate_jats_transform_payload_bytes(
    template_path: str | Path,
    mapping: SemanticMappingBody | dict[str, Any],
) -> int:
    path = Path(template_path)
    template_bytes = path.stat().st_size if path.is_file() else 0
    if isinstance(mapping, SemanticMappingBody):
        mapping_bytes = len(mapping.model_dump_json().encode("utf-8"))
    else:
        mapping_bytes = len(json.dumps(mapping, default=str).encode("utf-8"))
    return template_bytes + mapping_bytes


def assert_jats_transform_payload_under_limit(
    template_path: str | Path,
    mapping: SemanticMappingBody | dict[str, Any],
    *,
    limit: int | None = None,
) -> int:
    cap = limit if limit is not None else jats_max_transform_bytes()
    total = estimate_jats_transform_payload_bytes(template_path, mapping)
    if total > cap:
        raise JatsTransformTooLargeError(JATS_DOCUMENT_TOO_LARGE_DETAIL)
    return total


def is_jats_article_required_message(message: str) -> bool:
    lowered = message.lower()
    return "requires <article>" in lowered or "requires an <article>" in lowered
