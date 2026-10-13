from app.utils.book_paragraph_dedup import dedupe_ir_paragraph_nodes, dedupe_ir_section


def test_dedupe_removes_shorter_subsumed_ack_paragraph() -> None:
    short = {
        "type": "paragraph",
        "elements": [{"type": "text", "value": "As in the case of my previous book. " * 40}],
    }
    long_text = short["elements"][0]["value"] + "If I missed thanking anyone. " * 20
    long = {"type": "paragraph", "elements": [{"type": "text", "value": long_text}]}
    kept = dedupe_ir_paragraph_nodes([short, long])
    assert len(kept) == 1
    assert kept[0] is long


def test_dedupe_section_prefers_content_over_duplicate_paragraphs_field() -> None:
    node = {
        "type": "paragraph",
        "elements": [{"type": "text", "value": "Only once."}],
    }
    section = {
        "heading": "Acknowledgments",
        "heading_element": {"type": "heading", "elements": []},
        "level": 1,
        "content": [node],
        "paragraphs": [node],
        "subsections": [],
    }
    out = dedupe_ir_section(section)
    assert "paragraphs" not in out or not out.get("paragraphs")
    assert len(out["content"]) == 1
