from __future__ import annotations

from app.utils.isbn_selection import (
    book_root_xml_id,
    extract_isbn_entries,
    select_primary_isbn,
)


def test_prefers_cloth_isbn_over_electronic() -> None:
    text = (
        "ISBN 978-1-4985-4771-0 (electronic)\n"
        "ISBN 978-1-4985-4770-3 (cloth : alk. paper)"
    )
    entries = extract_isbn_entries(text)
    assert select_primary_isbn(entries) == "978-1-4985-4770-3"


def test_first_isbn13_when_no_cloth_marker() -> None:
    entries = [
        ("978-0-307-26929-6", None),
        ("978-0-307-26930-2", None),
    ]
    assert select_primary_isbn(entries) == "978-0-307-26929-6"


def test_book_root_xml_id_uses_isbn13_digits_only() -> None:
    assert book_root_xml_id("978-1-4985-4770-3") == "b-9781498547703"
    assert book_root_xml_id("1-4985-4770-3") is None
