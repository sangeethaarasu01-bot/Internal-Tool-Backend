"""Keep extraction MongoDB updates under the BSON document size limit."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.mongo_bson_limits import MONGODB_MAX_BSON_DOCUMENT_BYTES, bson_encoded_size

# Reserve space for field names and sibling extraction metadata on the same document.
_BSON_HEADROOM = 96 * 1024
_SEMANTIC_MAPPING_INLINE_MAX_BYTES = 2 * 1024 * 1024


class ExtractionMongoPayloadError(ValueError):
    """Extraction document cannot be stored in MongoDB even after compaction."""


def _document_bson_limit() -> int:
    return MONGODB_MAX_BSON_DOCUMENT_BYTES - _BSON_HEADROOM


def _persist_extraction_artifact(extraction_id: str, filename: str, payload: Any) -> str:
    out_dir = settings.outputs_dir / "extraction_artifacts" / extraction_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _projected_extraction_document(
    existing_doc: dict[str, Any],
    set_fields: dict[str, Any],
    unset_keys: list[str],
) -> dict[str, Any]:
    proj = copy.deepcopy({k: v for k, v in existing_doc.items() if k != "_id"})
    for key in unset_keys:
        if "." in key:
            parts = key.split(".")
            cursor: Any = proj
            for part in parts[:-1]:
                if not isinstance(cursor, dict):
                    cursor = None
                    break
                cursor = cursor.get(part)
            if isinstance(cursor, dict):
                cursor.pop(parts[-1], None)
        else:
            proj.pop(key, None)
    proj.update(set_fields)
    return proj


def _externalize_semantic_mapping(
    extraction_id: str,
    record: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _persist_extraction_artifact(extraction_id, "semantic_mapping.json", record)
    mapping = record.get("mapping") if isinstance(record.get("mapping"), dict) else {}
    body = mapping.get("body") if isinstance(mapping.get("body"), list) else []
    stub = {
        "document_id": record.get("document_id"),
        "scope": record.get("scope"),
        "prompt_version": record.get("prompt_version"),
        "warnings": (record.get("warnings") or [])[:32],
        "externalized": True,
        "storage_path": path,
        "body_node_count": len(body),
    }
    return stub, {"semantic_mapping_externalized": True, "semantic_mapping_path": path}


def load_extraction_artifact_file(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_phase1_from_extraction_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
    """Load phase1 from Mongo or from disk when externalized."""
    phase1 = doc.get("phase1") or (doc.get("result") or {}).get("phase1")
    if not isinstance(phase1, dict):
        return None
    if phase1.get("externalized"):
        path = (phase1.get("storage_path") or "").strip()
        if path and Path(path).is_file():
            loaded = load_extraction_artifact_file(path)
            return loaded if isinstance(loaded, dict) else None
        debug = doc.get("phase1_debug_paths") or {}
        fallback = (debug.get("phase1_document") or "").strip()
        if fallback and Path(fallback).is_file():
            loaded = load_extraction_artifact_file(fallback)
            return loaded if isinstance(loaded, dict) else None
        return None
    return phase1


def _externalize_phase1(
    extraction_id: str,
    phase1: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _persist_extraction_artifact(extraction_id, "phase1.json", phase1)
    pages = phase1.get("pages") if isinstance(phase1.get("pages"), list) else []
    stub = {
        "externalized": True,
        "storage_path": path,
        "page_count": len(pages),
    }
    return stub, {"phase1_externalized": True, "phase1_storage_path": path}


def _slim_result_structure(result: dict[str, Any]) -> bool:
    """Drop bulky structure fields when semantic IR is stored separately."""
    structure = result.get("structure")
    if not isinstance(structure, dict):
        return False
    changed = False
    if structure.pop("blocks", None) is not None:
        changed = True
    completeness = structure.get("completeness")
    if isinstance(completeness, dict) and completeness.pop("excluded_blocks", None) is not None:
        changed = True
    return changed


def _minimal_generated_xml_stub(
    record: dict[str, Any],
    *,
    extraction_id: str,
) -> dict[str, Any]:
    """Tiny ``generated_xml`` subdocument when the extraction row is near the BSON cap."""
    return {
        "output_format": record.get("output_format") or "docbook_5",
        "storage_mode": record.get("storage_mode") or "chapter_chunked",
        "scope": record.get("scope"),
        "mapping_source": record.get("mapping_source"),
        "prompt_version": record.get("prompt_version"),
        "full_book_xml_path": record.get("full_book_xml_path"),
        "output_filename": record.get("output_filename"),
        "extraction_id": extraction_id,
        "source_pdf_sha256": record.get("source_pdf_sha256"),
        "identity_verified": record.get("identity_verified"),
        "chapter_write_ok": record.get("chapter_write_ok"),
        "generated_at": record.get("generated_at"),
        "warnings": (record.get("warnings") or [])[:16],
        "mongo_stub": True,
    }


def _slim_generated_xml_record(record: dict[str, Any]) -> dict[str, Any]:
    slim = copy.deepcopy(record)
    slim.pop("xml_content", None)
    warnings = slim.get("warnings")
    if isinstance(warnings, list) and len(warnings) > 64:
        slim["warnings"] = warnings[:64] + [
            f"(truncated {len(warnings) - 64} additional warnings for MongoDB size)"
        ]
    manifest = slim.get("book_manifest")
    if isinstance(manifest, dict):
        units = manifest.get("units")
        if isinstance(units, list):
            manifest["units"] = [
                {
                    "document_id": u.get("document_id"),
                    "kind": u.get("kind"),
                    "title": u.get("title"),
                    "sequence": u.get("sequence"),
                    "status": u.get("status"),
                    "payload_bytes": u.get("payload_bytes"),
                }
                for u in units
                if isinstance(u, dict)
            ]
        slim["book_manifest"] = manifest
    return slim


def plan_extraction_mongo_update(
    existing_doc: dict[str, Any],
    set_fields: dict[str, Any],
    *,
    extraction_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """
    Build MongoDB ``$set`` / ``$unset`` payloads that keep the extraction document under 16MB.

    Large ``semantic_mapping`` bodies are written to ``outputs/extraction_artifacts/``.
    """
    ext_id = extraction_id or str(existing_doc.get("_id") or "unknown")
    flags: dict[str, Any] = {}
    set_copy = copy.deepcopy(set_fields)
    unset: dict[str, str] = {}
    limit = _document_bson_limit()

    def size() -> int:
        return bson_encoded_size(
            _projected_extraction_document(existing_doc, set_copy, list(unset.keys()))
        )

    if isinstance(existing_doc.get("result"), dict):
        if existing_doc["result"].get("phase1") and existing_doc.get("phase1"):
            unset["result.phase1"] = ""
            flags["result_phase1_deduplicated"] = True

    if (
        isinstance(set_copy.get("semantic_mapping"), dict)
        and bson_encoded_size(set_copy["semantic_mapping"]) > _SEMANTIC_MAPPING_INLINE_MAX_BYTES
    ):
        stub, ext_flags = _externalize_semantic_mapping(ext_id, set_copy["semantic_mapping"])
        set_copy["semantic_mapping"] = stub
        flags.update(ext_flags)

    if size() > limit and set_copy.get("generated_xml"):
        set_copy["generated_xml"] = _slim_generated_xml_record(set_copy["generated_xml"])

    if size() > limit and (
        set_copy.get("semantic_mapping") or existing_doc.get("semantic_mapping")
    ):
        set_copy.pop("semantic_mapping", None)
        unset["semantic_mapping"] = ""
        flags["semantic_mapping_dropped_from_mongo"] = True

    if size() > limit and set_copy.get("generated_xml"):
        gen = set_copy["generated_xml"]
        if isinstance(gen, dict):
            gen.pop("book_manifest", None)
            gen["storage_mode"] = gen.get("storage_mode") or "chapter_chunked"
            gen.setdefault(
                "warnings",
                [],
            ).append(
                "Book manifest omitted from extraction document (MongoDB 16MB limit); "
                "chapters are in book_documents and book_exports on disk."
            )
            set_copy["generated_xml"] = gen

    if size() > limit and isinstance(existing_doc.get("result"), dict):
        structure = existing_doc["result"].get("structure")
        if isinstance(structure, dict) and structure.get("blocks"):
            unset["result.structure.blocks"] = ""
            flags["structure_blocks_dropped"] = True
        if isinstance(structure, dict) and structure.get("completeness"):
            unset["result.structure.completeness"] = ""
            flags["structure_completeness_dropped"] = True

    if size() > limit and existing_doc.get("phase1"):
        phase1_raw = existing_doc["phase1"]
        if isinstance(phase1_raw, dict) and not phase1_raw.get("externalized"):
            stub, ext = _externalize_phase1(ext_id, phase1_raw)
            set_copy["phase1"] = stub
            flags.update(ext)
        else:
            unset["phase1"] = ""

    if size() > limit and set_copy.get("generated_xml"):
        set_copy["generated_xml"] = _minimal_generated_xml_stub(
            set_copy["generated_xml"],
            extraction_id=ext_id,
        )
        flags["generated_xml_minimal_stub"] = True

    if size() > limit:
        raise ExtractionMongoPayloadError(
            "MongoDB could not save this update: the extraction document would exceed "
            "Atlas's 16MB per-document limit. Start a new extraction for this PDF "
            "(recommended), or delete this extraction in Atlas and upload again. "
            "Full book XML is still written under data/outputs/book_exports/ when "
            "generate-xml succeeds before the final save."
        )

    return set_copy, unset, flags


def _strip_phase1_bulk_text(phase1: dict[str, Any]) -> bool:
    changed = False
    if phase1.pop("raw_text", None) is not None:
        changed = True
    if phase1.pop("normalized_text", None) is not None:
        changed = True
    for page in phase1.get("pages") or []:
        if isinstance(page, dict) and page.pop("raw_page_text", None) is not None:
            changed = True
    return changed


def compact_extraction_result_for_mongo(
    result_payload: dict[str, Any],
    phase1: dict[str, Any],
    *,
    extraction_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Return ``(result_payload, phase1, flags)`` safe to embed in an extraction document.

    Large book extractions externalize full ``raw_text`` to debug artifacts on disk;
    the API still serves structured phase1 without duplicating megabytes in MongoDB.
    """
    flags: dict[str, Any] = {}
    result_copy = copy.deepcopy(result_payload)
    phase1_copy = copy.deepcopy(phase1)

    probe = {
        "result": result_copy,
        "phase1": phase1_copy,
    }
    limit = MONGODB_MAX_BSON_DOCUMENT_BYTES - _BSON_HEADROOM
    if bson_encoded_size(probe) <= limit:
        return result_copy, phase1_copy, flags

    if _slim_result_structure(result_copy):
        flags["structure_blocks_omitted"] = True
    if bson_encoded_size({"result": result_copy, "phase1": phase1_copy}) <= limit:
        return result_copy, phase1_copy, flags

    if _strip_phase1_bulk_text(phase1_copy):
        flags["phase1_text_externalized"] = True
    probe["phase1"] = phase1_copy
    if bson_encoded_size(probe) <= limit:
        return result_copy, phase1_copy, flags

    # Drop duplicate phase1 inside result to avoid storing the same tree twice.
    if "phase1" in result_copy:
        result_copy.pop("phase1", None)
        flags["result_phase1_omitted"] = True
    if bson_encoded_size({"result": result_copy, "phase1": phase1_copy}) <= limit:
        return result_copy, phase1_copy, flags

    if extraction_id and bson_encoded_size({"result": result_copy, "phase1": phase1_copy}) > limit:
        stub, ext = _externalize_phase1(extraction_id, phase1_copy)
        phase1_copy = stub
        flags.update(ext)

    if bson_encoded_size({"result": result_copy, "phase1": phase1_copy}) > limit:
        flags["phase1_storage_warning"] = (
            "Extraction metadata still exceeds MongoDB size after compaction; "
            "see phase1_debug_paths on disk."
        )
    return result_copy, phase1_copy, flags
