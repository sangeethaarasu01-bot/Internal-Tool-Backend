"""Unit tests for generic table extraction helpers."""

from app.pipeline.table_extraction.geometry import camelot_bbox_to_fitz, iou
from app.pipeline.table_extraction.postprocess import fix_hyphenation, postprocess_table, remove_empty_rows_cols
from app.pipeline.table_extraction.validate import is_phantom, validate_table


def test_camelot_bbox_conversion() -> None:
    # PDF coords: y increases upward; table near top of letter page (~792pt)
    bbox = (72.0, 700.0, 400.0, 750.0)
    fitz = camelot_bbox_to_fitz(bbox, page_height=792.0)
    assert fitz[0] == 72.0
    assert fitz[2] == 400.0
    assert fitz[1] < fitz[3]


def test_iou_identical() -> None:
    a = [0.0, 0.0, 100.0, 100.0]
    assert iou(a, a) == 1.0


def test_hyphenation_merge() -> None:
    assert fix_hyphenation("cor- rected") == "corrected"


def test_postprocess_drops_empty_row() -> None:
    rows = [["A", "B"], ["", ""], ["1", "2"]]
    cleaned = remove_empty_rows_cols(rows)
    assert len(cleaned) == 2


def test_header_short_first_row() -> None:
    headers, body, _ = postprocess_table([["Col1", "Col2"], ["long value", "another"]])
    assert headers == ["Col1", "Col2"]
    assert body == [["long value", "another"]]


def test_phantom_single_cell() -> None:
    assert is_phantom([["only"]])


def test_validate_rejects_tiny_bbox() -> None:
    status, reason, _ = validate_table(
        [],
        [["a", "b"], ["c", "d"]],
        [0, 0, 10, 10],
        [],
        page_height=792.0,
        page_width=612.0,
        caption_detected=False,
        quality_score=0.5,
    )
    assert status == "rejected"
    assert reason == "bbox_too_small"
