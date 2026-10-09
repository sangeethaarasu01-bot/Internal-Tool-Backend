from app.services.extraction_mongo_payload import compact_extraction_result_for_mongo


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
