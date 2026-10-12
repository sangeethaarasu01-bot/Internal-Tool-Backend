from app.services.extraction_mongo_payload import (
    compact_extraction_result_for_mongo,
    plan_extraction_mongo_update,
)
from app.services.mongo_bson_limits import MONGODB_MAX_BSON_DOCUMENT_BYTES


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
