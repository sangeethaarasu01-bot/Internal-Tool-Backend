"""Phase 2A workflow helpers: template upload and scope resolution for extractions."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from lxml import etree

from app.database import utcnow
from app.services.llm.payload_compact import compact_template_schema_for_mongo
from app.services.scope_resolver import InvalidScopeError, resolve_scope
from app.services.template_format import UnsupportedTemplateRootError
from app.services.template_parser import TemplateParser

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")


class ExtractionWorkflowError(ValueError):
    """Raised when extraction workflow preconditions are not met."""


def ir_from_extraction_result(result: dict[str, Any]) -> dict[str, Any]:
    """Build partitioned IR JSON from a stored Stage 1 extraction result."""
    structure = result.get("structure") or {}
    semantic = structure.get("semantic")
    if not semantic:
        raise ExtractionWorkflowError("Extraction result has no semantic IR")
    ir = {key: value for key, value in semantic.items() if key != "tagged_output"}
    folios = structure.get("book_page_folios")
    if isinstance(folios, dict) and folios:
        ir["book_page_folios"] = folios
    return ir


def parse_template_xml(template_path: Path) -> dict[str, Any]:
    """Parse uploaded template XML into a template schema dict."""
    try:
        etree.parse(str(template_path))
    except etree.XMLSyntaxError as exc:
        raise ExtractionWorkflowError(f"Invalid XML template: {exc}") from exc

    try:
        schema = TemplateParser(template_path).parse()
    except UnsupportedTemplateRootError as exc:
        raise ExtractionWorkflowError(str(exc)) from exc
    return schema.model_dump(mode="json")


def build_template_record(
    *,
    template_path: Path,
    original_filename: str,
    schema: dict[str, Any],
    bound_extraction_id: str,
    bound_source_pdf_sha256: str | None,
    template_content_sha256: str | None = None,
    template_identity: dict | None = None,
) -> dict[str, Any]:
    """Build a template sub-document for MongoDB storage."""
    record: dict = {
        "template_id": uuid.uuid4().hex,
        "original_filename": original_filename,
        "file_path": str(template_path),
        "template_schema": compact_template_schema_for_mongo(schema),
        "created_at": utcnow(),
        "bound_extraction_id": bound_extraction_id,
        "bound_source_pdf_sha256": bound_source_pdf_sha256,
    }
    if template_content_sha256:
        record["template_content_sha256"] = template_content_sha256
    if template_identity:
        record["template_identity"] = template_identity
    return record


def template_storage_dir(extraction_id: str) -> Path:
    """Return the directory for template files associated with an extraction."""
    directory = Path(UPLOAD_DIR) / "extractions" / extraction_id / "templates"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def apply_scope_to_extraction(
    *,
    scope: str,
    result: dict[str, Any],
    template_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve scope against IR and optional template schema."""
    try:
        ir = ir_from_extraction_result(result)
    except ExtractionWorkflowError:
        raise

    schema = template_schema or {
        "template_name": "none",
        "template_source": "none",
        "root_tag": "article",
        "section_boundaries": {},
        "scope_markers": {},
        "required_paths": [],
        "tags": {},
        "llm_hints": {"must_not_hallucinate": [], "prefer_extract_over_generate": True},
    }
    return resolve_scope(scope, schema, ir)


def validate_extraction_object_id(extraction_id: str) -> ObjectId:
    """Validate and return a MongoDB ObjectId for an extraction id."""
    try:
        return ObjectId(extraction_id)
    except (InvalidId, TypeError) as exc:
        raise ExtractionWorkflowError("Invalid extraction id") from exc
