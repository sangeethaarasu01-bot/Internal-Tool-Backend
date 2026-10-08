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


def test_level_one_section_includes_right_column_intro_before_child() -> None:
    blocks = [
        _block("p6_iii", 6, 40.0, "III. WIDEBAND HARMONIC SUPPRESSION", "SECTION"),
        _block("p6_right", 6, 55.0, "Right column intro paragraph about harmonics.", "PARAGRAPH", column="RIGHT"),
        _block("p6_long", 6, 100.0, " ".join(["more intro"] * 80), "PARAGRAPH", column="RIGHT"),
        _block("p6_a", 6, 200.0, "A. Embedded SRR", "SUBSECTION"),
        _block("p6_a_body", 6, 220.0, "SRR body text.", "PARAGRAPH"),
    ]
    blocks[0].bbox = [90.0, 40.0, 250.0, 52.0]
    blocks[1].bbox = [310.0, 68.0, 560.0, 90.0]
    blocks[2].bbox = [310.0, 100.0, 560.0, 180.0]
    sections, _, _, _ = _build_structure(blocks)
    section_iii = next(s for s in sections if s.heading.startswith("III."))
    content = "\n\n".join((item.text or "") for item in section_iii.items)
    assert "Right column intro" in content
    assert "SRR body" not in content


def test_level_one_section_includes_intro_until_first_child() -> None:
    intro = " ".join(["intro"] * 120)
    blocks = [
        _block("p6_iii", 6, 40.0, "III. WIDEBAND HARMONIC SUPPRESSION", "SECTION"),
        _block("p6_intro", 6, 60.0, intro, "PARAGRAPH"),
        _block("p6_a", 6, 200.0, "A. Embedded SRR", "SUBSECTION"),
        _block("p6_a_body", 6, 220.0, "SRR body text.", "PARAGRAPH"),
    ]
    sections, _, _, _ = _build_structure(blocks)
    section_iii = next(s for s in sections if s.heading.startswith("III."))
    content = "\n\n".join((item.text or "") for item in section_iii.items)
    assert len(content) >= 400
    assert "SRR body" not in content
