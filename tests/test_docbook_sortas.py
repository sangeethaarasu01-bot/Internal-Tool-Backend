"""DocBook sortas derivation from title text."""

from app.utils.docbook_sortas import (
    compute_sortas_from_title,
    is_valid_sortas_for_title,
)


def test_drop_leading_article_preserves_rest_of_title() -> None:
    title = "The Political Poetry in the Wake of the Second Spanish Republic"
    sortas = compute_sortas_from_title(title)
    assert sortas == "Political Poetry in the Wake of the Second Spanish Republic"
    assert is_valid_sortas_for_title(title, sortas)


def test_sortas_keeps_colons_and_digits_from_title() -> None:
    title = "Political Poetry in: The Wake of the Second"
    sortas = compute_sortas_from_title(title)
    assert sortas == title
    assert is_valid_sortas_for_title(title, sortas)


def test_rejects_unrelated_template_sortas() -> None:
    title = "Political Poetry in the Wake of the Second Spanish Republic"
    assert not is_valid_sortas_for_title(title, "Political and Spiritual")
