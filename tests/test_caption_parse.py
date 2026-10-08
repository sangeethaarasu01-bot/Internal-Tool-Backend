from __future__ import annotations

from app.pipeline.phase1.caption_parse import parse_figure_number, subfigure_labels


def test_parse_figure_number_with_ligature_in_caption_body() -> None:
    caption = "Fig. 1.\nConﬁgurations of the proposed ﬁltering antenna. (a) Exploded view,"
    assert parse_figure_number(caption) == 1


def test_parse_figure_number_strict_period() -> None:
    assert parse_figure_number("FIGURE 2: Sample") == 2


def test_subfigure_labels_from_caption() -> None:
    labels = subfigure_labels("Fig. 9. Comparisons (a) Type-C. (b) Type-D.")
    assert labels == ["a", "b"]
