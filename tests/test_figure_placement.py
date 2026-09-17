"""Tests for figure IR construction and placement."""

from __future__ import annotations

from app.services.ir_builder import build_ir_node
from app.services.layout.semantic_builder import _build_figure_element, _reposition_figures_in_content
from app.models.document_structure import ProcessedBlock


def _block(block_id: str, text: str = "") -> ProcessedBlock:
    return ProcessedBlock(
        block_id=block_id,
        page_number=2,
        reading_order_index=0,
        column="LEFT",
        classification="PARAGRAPH",
        bbox=[0.0, 0.0, 100.0, 20.0],
        text=text,
        block_type="text",
    )


def test_build_figure_element_creates_caption_child() -> None:
    block = _block("p2_b9", "Fig. 1. Reference frames of sensorless controlled SPMSM.")
    figure = _build_figure_element(
        [block],
        "Reference frames of sensorless controlled SPMSM.",
        "Fig. 1.",
        0.9,
    )
    assert figure.type == "figure"
    assert figure.label == "Fig. 1."
    assert len(figure.children) == 1
    assert figure.children[0].type == "figure_caption"


def test_reposition_figures_places_after_referring_paragraph() -> None:
    para = build_ir_node("PARAGRAPH", "The frames are shown in Fig. 1 for clarity.")
    figure = build_ir_node(
        "FIGURE",
        "Reference frames of sensorless controlled SPMSM.",
        label="Fig. 1.",
        children=[build_ir_node("FIGURE_CAPTION", "Reference frames of sensorless controlled SPMSM.")],
    )
    next_para = build_ir_node("PARAGRAPH", "Next paragraph.")
    result = _reposition_figures_in_content([para, next_para, figure])
    assert [node.type for node in result] == ["paragraph", "figure", "paragraph"]
