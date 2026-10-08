from __future__ import annotations

from app.models.document_structure import ProcessedBlock
from app.services.layout.document_pipeline import _build_structure


def _block(
    block_id: str,
    page: int,
    y: float,
    text: str,
    classification: str = "PARAGRAPH",
    *,
    column: str = "LEFT",
) -> ProcessedBlock:
    return ProcessedBlock(
        block_id=block_id,
        page_number=page,
        reading_order_index=0,
        column=column,
        classification=classification,
        confidence=0.9,
        exclude_from_content=False,
        exclusion_reason=None,
        bbox=[50.0, y, 300.0, y + 12.0],
        text=text,
        block_type="text",
        dominant_font="Helvetica",
        dominant_font_size=10.0,
        is_bold=False,
    )


def test_two_column_page_orders_left_column_before_right() -> None:
    blocks = [
        _block("p6_iii", 6, 50.0, "III. WIDEBAND HARMONIC SUPPRESSION", "SECTION"),
        _block("p6_a", 6, 100.0, "A. Embedded SRR", "SUBSECTION"),
        _block("p6_iv", 6, 80.0, "IV. RESULTS AND DISCUSSION", "SECTION", column="RIGHT"),
        _block("p6_b", 6, 200.0, "B. Metasurface for Harmonic Suppression", "SUBSECTION"),
    ]
    sections, _, _, _ = _build_structure(blocks)
    headings = [s.heading for s in sections]
    assert headings.index("III. WIDEBAND HARMONIC SUPPRESSION") < headings.index(
        "B. Metasurface for Harmonic Suppression"
    )
    assert headings.index("B. Metasurface for Harmonic Suppression") < headings.index(
        "IV. RESULTS AND DISCUSSION"
    )
    metasurface = next(s for s in sections if s.heading.startswith("B. Metasurface"))
    assert metasurface.parent_heading == "III. WIDEBAND HARMONIC SUPPRESSION"


def test_conclusion_section_excludes_references_heading() -> None:
    blocks = [
        _block("p6_v", 6, 80.0, "V. CONCLUSION", "SECTION"),
        _block("p6_body", 6, 100.0, "In this communication, a filtering antenna was proposed.", "PARAGRAPH"),
        _block("p6_refs", 6, 200.0, "REFERENCES", "SECTION"),
        _block("p6_ref1", 6, 220.0, "[1] A. Author, Title, 2020.", "REFERENCE_TEXT"),
    ]
    sections, _, references, _ = _build_structure(blocks)
    conclusion = next(s for s in sections if s.heading.startswith("V."))
    assert "REFERENCES" not in conclusion.heading
    assert all("REFERENCES" not in (item.text or "") for item in conclusion.items)
    assert len(references) == 1
