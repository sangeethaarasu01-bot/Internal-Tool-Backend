"""Tests for geometry-based table grid reconstruction."""

from __future__ import annotations

from app.models.document_structure import ProcessedBlock
from app.services.layout.table_grid_builder import reconstruct_table_grid_from_blocks


def _processed(block_id: str, text: str, bbox: list[float]) -> ProcessedBlock:
    return ProcessedBlock(
        block_id=block_id,
        page_number=1,
        reading_order_index=0,
        column="LEFT",
        classification="PARAGRAPH",
        bbox=bbox,
        text=text,
        block_type="text",
    )


def test_reconstruct_merges_multiline_column_headers() -> None:
    blocks = [
        _processed("h0", "Sample", [80, 100, 120, 115]),
        _processed("h1", "MetricA", [160, 100, 200, 115]),
        _processed("h2", "(u)", [160, 118, 200, 133]),
        _processed("h3", "MetricB", [240, 100, 280, 115]),
        _processed("d0", "X1", [80, 150, 110, 165]),
        _processed("d1", "1.23", [160, 150, 200, 165]),
        _processed("d2", "4.56", [240, 150, 280, 165]),
    ]
    rows = reconstruct_table_grid_from_blocks(blocks)
    assert rows is not None
    assert rows[0] == ["Sample", "MetricA (u)", "MetricB"]
    assert rows[1] == ["X1", "1.23", "4.56"]


def test_reconstruct_returns_none_for_sparse_blocks() -> None:
    blocks = [
        _processed("a", "only", [80, 100, 120, 115]),
        _processed("b", "two", [160, 100, 200, 115]),
    ]
    assert reconstruct_table_grid_from_blocks(blocks) is None
