"""Tests for two-column reading order."""

from __future__ import annotations

from app.models.extraction import PageExtraction, TextBlock
from app.services.layout.reading_order import order_page_blocks


def _text_block(block_id: str, text: str, bbox: list[float]) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        type="text",
        bbox=bbox,
        text=text,
        spans=[],
    )


def test_order_page_blocks_interleaves_columns_by_row() -> None:
    blocks = [
        _text_block("l1", "Left top", [40, 100, 250, 120]),
        _text_block("l2", "Left bottom", [40, 300, 250, 320]),
        _text_block("r1", "Right top", [320, 110, 560, 130]),
        _text_block("r2", "Right bottom", [320, 310, 560, 330]),
    ]
    page = PageExtraction(
        page_number=2,
        width=600,
        height=800,
        text_char_count=sum(len(block.text) for block in blocks),
        requires_ocr=False,
        blocks=blocks,
    )
    ordered = order_page_blocks(page)
    assert [block.block_id for block in ordered] == ["l1", "r1", "l2", "r2"]
