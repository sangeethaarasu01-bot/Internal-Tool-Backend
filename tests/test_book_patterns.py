from __future__ import annotations

from types import SimpleNamespace

from app.services.layout.book_patterns import (
    is_book_back_matter_heading,
    parse_book_title_block_heading,
    reorder_book_body_sections,
)


def test_parse_book_title_block_heading_numbered_and_chapter_titles() -> None:
    book_title = "Political Poetry in the Wake of the Second Spanish Republic"
    parsed = parse_book_title_block_heading(
        "1 Intellectuals and the Second Spanish Republic",
        book_title=book_title,
    )
    assert parsed is not None
    assert parsed.heading.startswith("Chapter 1:")
    parsed = parse_book_title_block_heading(
        "Rafael Alberti: Between Aesthetics and Politics",
        book_title=book_title,
    )
    assert parsed is not None
    assert "Alberti" in parsed.heading


def test_parse_book_title_block_heading_skips_duplicate_title() -> None:
    title = "Political Poetry in the Wake of the Second Spanish Republic"
    assert parse_book_title_block_heading(title, book_title=title) is None


def test_reorder_book_body_sections() -> None:
    index = SimpleNamespace(heading="Index")
    about = SimpleNamespace(heading="About the Author")
    ch1 = SimpleNamespace(heading="Chapter 1: Intro")
    ordered = reorder_book_body_sections([index, about, ch1])
    assert [s.heading for s in ordered] == ["Chapter 1: Intro", "Index", "About the Author"]
    assert is_book_back_matter_heading("Index")
