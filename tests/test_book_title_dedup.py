from __future__ import annotations

from app.utils.book_title_dedup import collapse_repeated_title_phrase


def test_collapse_duplicated_title_phrase() -> None:
    title = "Political Poetry in the Wake of the Second Spanish Republic"
    doubled = f"{title} {title}"
    assert collapse_repeated_title_phrase(doubled) == title


def test_collapse_leaves_single_title_unchanged() -> None:
    title = "Political Poetry in the Wake of the Second Spanish Republic"
    assert collapse_repeated_title_phrase(title) == title
