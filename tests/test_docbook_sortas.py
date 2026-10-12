"""DocBook sortas derivation from title text."""

from app.utils.docbook_sortas import (
    compute_sortas_from_title,
    is_valid_sortas_for_title,
)


def test_drop_leading_article() -> None:
    assert compute_sortas_from_title("The Political Poetry") == "Political Poetry"


def test_leading_year_to_words() -> None:
    assert compute_sortas_from_title("1984") == "Nineteen Eighty-Four"
    assert compute_sortas_from_title("1984 A Novel").startswith("Nineteen Eighty-Four")


def test_colon_removed_from_sortas() -> None:
    sortas = compute_sortas_from_title("Political Poetry in: The Wake of the Second")
    assert sortas is not None
    assert ":" not in sortas
    assert "Political Poetry" in sortas


def test_rejects_unrelated_template_sortas() -> None:
    title = "Political Poetry in: The Wake of the Second"
    assert not is_valid_sortas_for_title(title, "Political and Spiritual")


def test_accepts_sortas_from_same_title() -> None:
    title = "Political Poetry in the Wake of the Second Spanish Republic"
    sortas = compute_sortas_from_title(title)
    assert sortas is not None
    assert is_valid_sortas_for_title(title, sortas)
