from __future__ import annotations

from app.services.layout.book_author_bio import extract_author_name_from_blurb_text
from app.utils.book_blurb_text import clean_personblurb_text


def test_dehyphenate_and_footer_page_number() -> None:
    raw = "He teaches at Pittsburg State Univer- sity and writes on pedagogy. 159"
    cleaned = clean_personblurb_text(raw)
    assert "University" in cleaned
    assert "159" not in cleaned
    assert cleaned.endswith("pedagogy.")


def test_possessive_apostrophe_and_inc() -> None:
    raw = "Grant D. Moss is a professor. He earned his Master's degree from Rowman Inc."
    cleaned = clean_personblurb_text(raw)
    assert "Master\u2019s" in cleaned
    assert "Inc." in cleaned
    assert cleaned.endswith("Inc.")


def test_typography_curly_apostrophe_all_text() -> None:
    from app.utils.book_text_typography import apply_book_typography

    assert "\u2019" in apply_book_typography("Bachelor's and Master's")


def test_typography_curly_double_quotes() -> None:
    from app.utils.book_text_typography import apply_book_typography

    result = apply_book_typography('He said "hello" to the class.')
    assert "\u201c" in result and "\u201d" in result


def test_author_name_from_blurb_opener() -> None:
    blurb = "Grant D. Moss is an Associate Professor of Spanish at Pittsburg State University."
    assert extract_author_name_from_blurb_text(blurb) == "Grant D. Moss"
