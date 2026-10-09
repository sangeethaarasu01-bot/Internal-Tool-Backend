"""Persist DocBook 5.0 books as a manifest plus per-chapter MongoDB documents."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.database import book_documents_col
from app.services.docbook_book_chunking import (
    BookChunk,
    BookManifest,
    DocBookChunkingError,
    chunk_docbook_book_xml,
    reassemble_book_xml_from_chunks,
)
from app.services.mongo_bson_limits import (
    MONGODB_MAX_BSON_DOCUMENT_BYTES,
    bson_encoded_size,
    mongodb_max_payload_bytes,
)

logger = logging.getLogger(__name__)

STORAGE_MODE_CHUNKED = "chapter_chunked"


@dataclass
class ChapterWriteResult:
    document_id: str
    ok: bool
    error: str | None = None


@dataclass
class BookWriteResult:
    manifest: dict[str, Any]
    writes: list[ChapterWriteResult] = field(default_factory=list)
    all_ok: bool = False

    @property
    def success_count(self) -> int:
        return sum(1 for w in self.writes if w.ok)


def _storage_key(extraction_id: str, document_id: str) -> str:
    return f"{extraction_id}::{document_id}"


def _validate_chunk_record(record: dict[str, Any]) -> None:
    size = bson_encoded_size(record)
    limit = MONGODB_MAX_BSON_DOCUMENT_BYTES - (64 * 1024)
    if size > limit:
        raise DocBookChunkingError(
            f"Chunk record for {record.get('document_id')} BSON size {size} exceeds limit {limit}."
        )


def write_book_chunks(
    extraction_id: str,
    book_xml: str,
    *,
    only_document_ids: set[str] | None = None,
    max_payload_bytes: int | None = None,
    col: Collection | None = None,
) -> BookWriteResult:
    """
    Chunk book XML, validate payload sizes, upsert manifest units and chapter documents.

    Idempotent: repeated calls replace the same ``_id`` keys without duplicating rows.
    """
    cap = max_payload_bytes if max_payload_bytes is not None else mongodb_max_payload_bytes()
    manifest_obj, chunks = chunk_docbook_book_xml(
        book_xml,
        extraction_id=extraction_id,
        max_payload_bytes=cap,
    )
    manifest = manifest_obj.to_dict()
    collection = col or book_documents_col()
    now = datetime.now(timezone.utc)
    writes: list[ChapterWriteResult] = []

    for chunk in chunks:
        if only_document_ids is not None and chunk.document_id not in only_document_ids:
            continue

        record = {
            "_id": _storage_key(extraction_id, chunk.document_id),
            "extraction_id": extraction_id,
            "book_id": manifest["book_id"],
            "document_id": chunk.document_id,
            "kind": chunk.kind,
            "sequence": chunk.sequence,
            "parent_part_id": chunk.parent_part_id,
            "split_parent_id": chunk.split_parent_id,
            "split_index": chunk.split_index,
            "payload_bytes": chunk.payload_bytes,
            "xml_content": chunk.xml_fragment,
            "updated_at": now,
        }
        try:
            _validate_chunk_record(record)
            collection.replace_one({"_id": record["_id"]}, record, upsert=True)
            writes.append(ChapterWriteResult(document_id=chunk.document_id, ok=True))
        except (DocBookChunkingError, PyMongoError) as exc:
            logger.warning(
                "Chapter write failed extraction=%s doc=%s: %s",
                extraction_id,
                chunk.document_id,
                exc,
            )
            writes.append(
                ChapterWriteResult(
                    document_id=chunk.document_id,
                    ok=False,
                    error=str(exc),
                )
            )

    _apply_write_status_to_manifest(manifest, writes)
    manifest["status"] = "complete" if all(w.ok for w in writes) else "partial"
    manifest["written_at"] = now.isoformat()

    result = BookWriteResult(
        manifest=manifest,
        writes=writes,
        all_ok=all(w.ok for w in writes),
    )
    return result


def _apply_write_status_to_manifest(
    manifest: dict[str, Any],
    writes: list[ChapterWriteResult],
) -> None:
    by_id = {w.document_id: w for w in writes}
    for unit in manifest.get("units") or []:
        doc_id = unit.get("document_id")
        if doc_id in by_id:
            unit["status"] = "written" if by_id[doc_id].ok else "failed"
            if by_id[doc_id].error:
                unit["error"] = by_id[doc_id].error


def load_chunk_xml_map(extraction_id: str, *, col: Collection | None = None) -> dict[str, str]:
    collection = col or book_documents_col()
    out: dict[str, str] = {}
    for doc in collection.find({"extraction_id": extraction_id}):
        doc_id = doc.get("document_id")
        xml = doc.get("xml_content")
        if doc_id and xml:
            out[str(doc_id)] = str(xml)
    return out


def reassemble_stored_book(extraction_id: str, manifest: dict[str, Any]) -> str:
    chunks_by_id = load_chunk_xml_map(extraction_id)
    return reassemble_book_xml_from_chunks(manifest, chunks_by_id)


def retry_failed_chapters(
    extraction_id: str,
    book_xml: str,
    manifest: dict[str, Any],
    *,
    max_payload_bytes: int | None = None,
) -> BookWriteResult:
    failed_ids = {
        str(u["document_id"])
        for u in (manifest.get("units") or [])
        if u.get("status") == "failed"
    }
    if not failed_ids:
        return BookWriteResult(manifest=manifest, writes=[], all_ok=True)
    return write_book_chunks(
        extraction_id,
        book_xml,
        only_document_ids=failed_ids,
        max_payload_bytes=max_payload_bytes,
    )


def generated_xml_record_for_chunked_book(
    *,
    scope: str,
    mapping_source: str,
    prompt_version: str | None,
    warnings: list[str],
    manifest: dict[str, Any],
    write_result: BookWriteResult,
) -> dict[str, Any]:
    """Mongo-safe ``generated_xml`` payload without inline full-book ``xml_content``."""
    extra_warnings = list(warnings)
    if not write_result.all_ok:
        extra_warnings.append(
            f"Book chapter storage incomplete: {write_result.success_count}/"
            f"{len(write_result.writes)} units written."
        )
    else:
        extra_warnings.append(
            f"DocBook book stored as {manifest.get('total_unit_count')} chapter-level documents."
        )
    return {
        "scope": scope,
        "mapping_source": mapping_source,
        "prompt_version": prompt_version,
        "output_format": "docbook_5",
        "storage_mode": STORAGE_MODE_CHUNKED,
        "book_manifest": manifest,
        "xml_content": None,
        "warnings": extra_warnings,
        "generated_at": datetime.now(timezone.utc),
        "chapter_write_ok": write_result.all_ok,
    }
