from __future__ import annotations

from app.models.document_structure import ProcessedBlock
from app.services.layout.semantic_builder import _book_paragraph_segments, _book_page_spans_for_blocks
from app.utils.text_utils import split_book_visual_paragraphs


def _block(bid: str, page: int, text: str, y0: float, y1: float) -> ProcessedBlock:
    return ProcessedBlock(
        block_id=bid,
        page_number=page,
        reading_order_index=0,
        column="FULL_WIDTH",
        classification="PARAGRAPH",
        confidence=0.9,
        bbox=[72.0, y0, 400.0, y1],
        text=text,
        block_type="text",
        dominant_font_size=10.0,
    )


def test_split_visual_paragraphs_after_erroneous() -> None:
    blob = (
        "works are pure propaganda without any poetry would also be erroneous. "
        "This text does not contain detailed analysis"
    )
    parts = split_book_visual_paragraphs(blob)
    assert len(parts) >= 2
    assert parts[0].endswith("erroneous.")
    assert parts[1].startswith("This text")


def test_book_paragraph_segments_use_vertical_gap() -> None:
    blocks = [
        _block("a", 8, "First paragraph line one.", 100, 112),
        _block("b", 8, "First paragraph line two.", 112, 124),
        _block("c", 8, "Second paragraph starts here.", 150, 162),
    ]
    segments = _book_paragraph_segments(blocks)
    assert len(segments) == 2
    assert "Second paragraph" in segments[1][1]


def test_page_spans_across_pdf_pages() -> None:
    blocks = [
        _block("a", 7, "Reaching a large readership for poetry was", 600, 612),
        _block("b", 8, "a feat in and of itself.", 80, 92),
    ]
    spans = _book_page_spans_for_blocks(blocks)
    assert len(spans) == 2
    assert spans[0]["page"] == 7
    assert spans[1]["page"] == 8
