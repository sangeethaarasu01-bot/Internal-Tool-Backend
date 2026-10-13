from app.services.extraction_mongo_payload import (
    apply_warnings_to_planned_generated_xml,
    compact_extraction_result_for_mongo,
    plan_extraction_mongo_update,
    resolve_extraction_result_from_doc,
)
from app.services.mongo_bson_limits import MONGODB_MAX_BSON_DOCUMENT_BYTES, bson_encoded_size


def test_compact_strips_duplicate_raw_text() -> None:
    huge = "x" * (9 * 1024 * 1024)
    phase1 = {"raw_text": huge, "normalized_text": huge, "pages": [{"raw_page_text": "p"}]}
    result = {"phase1": phase1, "document": {"page_count": 1}}
    compact_result, compact_phase1, flags = compact_extraction_result_for_mongo(result, phase1)
    assert flags.get("phase1_text_externalized") is True
    assert "raw_text" not in compact_phase1
    assert "normalized_text" not in compact_phase1
    assert compact_result.get("phase1") is None or "phase1" not in compact_result or flags.get(
        "result_phase1_omitted"
    )


def test_plan_update_externalizes_large_semantic_mapping(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    huge_body = [{"semantic_type": "paragraph", "text": "note " * 5000} for _ in range(400)]
    mapping = {
        "document_id": "abc",
        "scope": "full",
        "prompt_version": "v1",
        "mapping": {"front": {}, "body": huge_body, "back": {}},
        "warnings": [],
    }
    doc = {"_id": "abc", "result": {"document": {"page_count": 1}}, "phase1": {"pages": []}}
    set_fields, unset, flags = plan_extraction_mongo_update(
        doc,
        {"semantic_mapping": mapping},
        extraction_id="abc",
    )
    assert flags.get("semantic_mapping_externalized")
    assert set_fields["semantic_mapping"].get("externalized") is True
    assert unset == {}


def test_plan_update_drops_duplicate_result_phase1_when_large() -> None:
    filler = "z" * (15 * 1024 * 1024)
    doc = {
        "_id": "x",
        "result": {"blob": filler, "phase1": {"nested": True}},
        "phase1": {"pages": []},
        "semantic_mapping": {"mapping": {"body": [{"text": "old"}]}},
    }
    generated = {
        "output_format": "docbook_5",
        "storage_mode": "chapter_chunked",
        "xml_content": None,
        "book_manifest": {"units": [{"document_id": "ch1", "kind": "chapter"}]},
        "warnings": [],
    }
    set_fields, unset, flags = plan_extraction_mongo_update(
        doc,
        {"generated_xml": generated},
        extraction_id="x",
    )
    assert unset.get("result.phase1") == ""
    assert bson_size_under_limit(doc, set_fields, unset)


def test_compact_externalizes_structure_for_large_book_ir(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    huge_semantic = {
        "front": {},
        "body": [{"text": "paragraph " * 800, "semantic_type": "paragraph"} for _ in range(2500)],
        "back": {},
    }
    structure = {"semantic": huge_semantic, "blocks": [{"text": "b"}]}
    phase1 = {"pages": [{"page_number": i, "paragraphs": [{"text": "x" * 2000}]} for i in range(311)]}
    result = {"structure": structure, "document": {"page_count": 311}}
    compact_result, compact_phase1, flags = compact_extraction_result_for_mongo(
        result, phase1, extraction_id="book311"
    )
    assert flags.get("structure_externalized") or flags.get("phase1_externalized")
    stub = compact_result.get("structure") or {}
    if stub.get("externalized"):
        assert (tmp_path / "outputs" / "extraction_artifacts" / "book311" / "structure.json").is_file()
    cmd = bson_encoded_size({"$set": {"result": compact_result, "phase1": compact_phase1}})
    assert cmd < MONGODB_MAX_BSON_DOCUMENT_BYTES


def test_plan_initial_extraction_save_under_update_command_limit(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    huge_semantic = {
        "front": {},
        "body": [{"text": "word " * 600, "semantic_type": "paragraph"} for _ in range(2000)],
        "back": {},
    }
    structure = {"semantic": huge_semantic}
    phase1 = {"pages": [{"page_number": i, "paragraphs": [{"text": "y" * 1500}]} for i in range(311)]}
    result = {"structure": structure, "document": {"page_count": 311}, "phase1": phase1}
    existing: dict = {}
    update_fields = {
        "status": "completed",
        "result": result,
        "phase1": phase1,
        "page_count": 311,
    }
    set_fields, unset, flags = plan_extraction_mongo_update(
        existing, update_fields, extraction_id="large-save"
    )
    cmd_size = bson_encoded_size({"$set": set_fields, "$unset": unset})
    assert cmd_size < MONGODB_MAX_BSON_DOCUMENT_BYTES - 96 * 1024
    struct = (set_fields.get("result") or {}).get("structure") or {}
    phase1_field = set_fields.get("phase1") or {}
    assert struct.get("externalized") or phase1_field.get("externalized") or bson_encoded_size(
        {"result": set_fields.get("result"), "phase1": phase1_field}
    ) < 12 * 1024 * 1024


def test_resolve_extraction_result_loads_externalized_structure(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    structure = {"semantic": {"front": {}, "body": [{"text": "hello"}], "back": {}}}
    result_in, _, _ = compact_extraction_result_for_mongo(
        {"structure": structure},
        {"pages": []},
        extraction_id="hydrate",
    )
    doc = {"result": result_in, "phase1": {"pages": []}}
    resolved = resolve_extraction_result_from_doc(doc)
    assert resolved["structure"]["semantic"]["body"][0]["text"] == "hello"


def test_apply_warnings_keeps_slim_generated_xml_without_xml_content() -> None:
    set_fields = {
        "generated_xml": {
            "output_format": "docbook_5",
            "storage_mode": "chapter_chunked",
            "mongo_stub": True,
            "warnings": [],
        }
    }
    apply_warnings_to_planned_generated_xml(set_fields, ["warn-a", "warn-b"])
    gen = set_fields["generated_xml"]
    assert "xml_content" not in gen
    assert "warn-a" in gen["warnings"] and "warn-b" in gen["warnings"]


def test_plan_update_idempotent_retry_same_externalized_artifacts(tmp_path, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    mapping = {
        "document_id": "retry1",
        "scope": "full",
        "prompt_version": "v1",
        "mapping": {"front": {}, "body": [{"text": "t " * 4000} for _ in range(500)], "back": {}},
        "warnings": [],
    }
    doc = {"_id": "retry1", "result": {"document": {"page_count": 1}}, "phase1": {"pages": []}}
    first_set, _, _ = plan_extraction_mongo_update(
        doc, {"semantic_mapping": mapping}, extraction_id="retry1"
    )
    doc_after = {**doc, "semantic_mapping": first_set["semantic_mapping"]}
    second_set, _, flags2 = plan_extraction_mongo_update(
        doc_after, {"semantic_mapping": mapping}, extraction_id="retry1"
    )
    assert second_set["semantic_mapping"].get("storage_path") == first_set["semantic_mapping"].get(
        "storage_path"
    )
    assert flags2.get("semantic_mapping_externalized") is True


def bson_size_under_limit(doc, set_fields, unset) -> bool:
    from app.services.extraction_mongo_payload import plan_extraction_mongo_update
    from app.services.mongo_bson_limits import bson_encoded_size

    limit = MONGODB_MAX_BSON_DOCUMENT_BYTES - 96 * 1024
    # Re-plan with same fields should not raise if under limit.
    try:
        plan_extraction_mongo_update(doc, set_fields, extraction_id="x")
    except Exception:
        return False
    proj = {k: v for k, v in doc.items() if k != "_id"}
    for key in unset:
        if key == "semantic_mapping":
            proj.pop("semantic_mapping", None)
    proj.update(set_fields)
    return bson_encoded_size(proj) <= limit
