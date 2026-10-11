"""Book running header detection and paragraph merge across page breaks."""

from __future__ import annotations

from app.models.extraction import TextBlock, TextLine, TextSpan
from app.services.layout.text_filter import classify_content_block
from app.utils.book_running_headers import is_book_running_header_text
from app.utils.text_utils import merge_block_texts


def test_is_book_running_header_text() -> None:
    assert is_book_running_header_text("122 Chapter 9")
    assert is_book_running_header_text("12 CHAPTER 3")
    assert not is_book_running_header_text("A paradigmatic shift can occur in many ways.")


def test_classify_book_running_header_excluded() -> None:
    block = TextBlock(
        block_id="p140_b0",
        type="text",
        bbox=[48.0, 36.0, 227.0, 45.0],
        text="122 Chapter 9",
        lines=[
            TextLine(
                line_id="l0",
                bbox=[48.0, 36.0, 227.0, 45.0],
                text="122 Chapter 9",
                spans=[
                    TextSpan(
                        text="122 Chapter 9",
                        bbox=[48.0, 36.0, 227.0, 45.0],
                        font="Times",
                        size=9.0,
                        flags=0,
                    )
                ],
            )
        ],
    )
    decision = classify_content_block(
        block,
        140,
        418.0,
        666.0,
        in_references=False,
        running_header_pages={},
        page_number_candidates={},
        body_font_size=10.0,
        book_mode=True,
    )
    assert decision.exclude_from_content
    assert decision.classification == "RUNNING_HEADER"


def test_merge_block_texts_keeps_space_between_whole_words() -> None:
    part_a = (
        "A paradigmatic shift can occur in many ways. Several stages occur as"
    )
    part_b = "one transitions from the old system to the new paradigm"
    merged = merge_block_texts([part_a, part_b])
    assert "occur as one" in merged
    assert "asone" not in merged
    assert merge_block_texts(["give up after", "repeated encounters"]).startswith(
        "give up after repeated"
    )


def _block(block_id: str, text: str, bbox: list[float]) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        type="text",
        bbox=bbox,
        text=text,
        lines=[
            TextLine(
                line_id=f"{block_id}_l0",
                bbox=bbox,
                text=text,
                spans=[
                    TextSpan(
                        text=text,
                        bbox=bbox,
                        font="Times",
                        size=10.0,
                        flags=0,
                    )
                ],
            )
        ],
    )

