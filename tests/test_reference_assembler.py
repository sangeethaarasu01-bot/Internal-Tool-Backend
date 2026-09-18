"""Tests for PDF-numbered bibliography assembly."""

from __future__ import annotations

import pytest
from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.layout.document_pipeline import process_document_structure
from app.services.xml_generator import generate_jats_xml
from app.utils.reference_assembler import (
    ReferenceParsingError,
    assemble_references_from_blocks,
    assemble_references_from_buffer,
    parse_reference_number,
    reference_block_sort_key,
    sort_reference_section_blocks,
    validate_reference_sequence,
    AssembledReference,
)
from tests.test_semantic_document import _block, _page, _raw


def _processed_block(
    block_id: str,
    text: str,
    *,
    page_number: int = 8,
    column: str = "LEFT",
    y0: float = 100.0,
    reading_order_index: int = 0,
):
    from app.models.document_structure import ProcessedBlock

    return ProcessedBlock(
        block_id=block_id,
        page_number=page_number,
        reading_order_index=reading_order_index,
        column=column,
        classification="REFERENCE_TEXT",
        confidence=0.9,
        exclude_from_content=False,
        exclusion_reason=None,
        bbox=[50, y0, 550, y0 + 15],
        text=text,
        block_type="text",
        dominant_font="Helvetica",
        dominant_font_size=10.0,
        is_bold=False,
    )


def test_parse_reference_number_reads_pdf_label() -> None:
    assert parse_reference_number("[1]") == 1
    assert parse_reference_number("[159] World Health Organization") == 159


def test_column_major_sort_uses_bbox_geometry_not_block_column_field() -> None:
    # Blocks misclassified as FULL_WIDTH should still read left column before right column.
    blocks = [
        _processed_block(
            "p1_b1",
            "[1] First reference.",
            column="FULL_WIDTH",
            y0=100,
            reading_order_index=0,
        ),
        _processed_block(
            "p1_b2",
            "[3] Third reference.",
            column="FULL_WIDTH",
            y0=100,
            reading_order_index=1,
        ),
        _processed_block(
            "p1_b3",
            "[2] Second reference.",
            column="FULL_WIDTH",
            y0=120,
            reading_order_index=2,
        ),
        _processed_block(
            "p1_b4",
            "[4] Fourth reference.",
            column="FULL_WIDTH",
            y0=120,
            reading_order_index=3,
        ),
    ]
    blocks[0].bbox = [50, 100, 280, 115]
    blocks[1].bbox = [310, 100, 540, 115]
    blocks[2].bbox = [50, 120, 280, 135]
    blocks[3].bbox = [310, 120, 540, 135]

    refs = assemble_references_from_blocks(blocks, validate=True)
    assert [parse_reference_number(ref.label) for ref in refs] == [1, 2, 3, 4]


def test_column_major_sort_reads_left_column_before_right_column() -> None:
    # Row-interleaved reading order would yield [1, 3, 2, 4]; column-major yields [1, 2, 3, 4].
    blocks = [
        _processed_block("p1_b1", "[1] First reference.", column="LEFT", y0=100, reading_order_index=0),
        _processed_block("p1_b2", "[3] Third reference.", column="RIGHT", y0=100, reading_order_index=1),
        _processed_block("p1_b3", "[2] Second reference.", column="LEFT", y0=120, reading_order_index=2),
        _processed_block("p1_b4", "[4] Fourth reference.", column="RIGHT", y0=120, reading_order_index=3),
    ]
    blocks[0].bbox = [50, 100, 280, 115]
    blocks[1].bbox = [310, 100, 540, 115]
    blocks[2].bbox = [50, 120, 280, 135]
    blocks[3].bbox = [310, 120, 540, 135]
    sorted_blocks = sort_reference_section_blocks(blocks)
    numbers = []
    for block in sorted_blocks:
        label = parse_reference_number(block.text)
        if label is not None:
            numbers.append(label)
    assert numbers == [1, 2, 3, 4]

    refs = assemble_references_from_blocks(blocks, validate=True)
    assert [parse_reference_number(ref.label) for ref in refs] == [1, 2, 3, 4]


def test_validate_reference_sequence_rejects_gaps_and_duplicates() -> None:
    refs = [
        AssembledReference(1, "[1]", "[1] A", [], [], None, 1.0),
        AssembledReference(3, "[3]", "[3] C", [], [], None, 1.0),
    ]
    with pytest.raises(ReferenceParsingError, match="order mismatch"):
        validate_reference_sequence(refs)

    dupes = [
        AssembledReference(1, "[1]", "[1] A", [], [], None, 1.0),
        AssembledReference(1, "[1]", "[1] B", [], [], None, 1.0),
    ]
    with pytest.raises(ReferenceParsingError, match="Duplicate"):
        validate_reference_sequence(dupes)


def test_merge_standalone_reference_labels_attaches_orphan_number() -> None:
    blocks = [
        _processed_block("p8_b2", "[1]", y0=130),
        _processed_block("p8_b3", "World Health Organization. Breast Cancer.", y0=131),
        _processed_block("p8_b4", "[2]", y0=150),
        _processed_block(
            "p8_b5",
            "H. Sung, J. Ferlay, R. L. Siegel, vol. 71, pp. 209-249, May 2021.",
            y0=151,
        ),
    ]
    refs = assemble_references_from_blocks(blocks, validate=True)
    assert len(refs) == 2
    assert refs[0].label == "[1]"
    assert refs[1].label == "[2]"


def test_assemble_references_preserves_multiline_boundaries() -> None:
    blocks = [
        _processed_block("p8_b2", "[1] World Health Organization. Breast Cancer: Prevention and Control."),
        _processed_block("p8_b3", "Accessed:Mar.16,2024.[Online].Available:https://www.who.int/news"),
        _processed_block("p8_b4", "room/fact-sheets/detail/breast-cancer", y0=162),
        _processed_block("p8_b5", "[2] H. Sung, J. Ferlay, R. L. Siegel, vol. 71, pp. 209-249, May 2021.", y0=190),
        _processed_block("p8_b6", "[3] G. Dileep, Another paper, IEEE, 2020.", y0=250),
    ]
    refs = assemble_references_from_blocks(blocks, validate=True)
    assert len(refs) == 3
    assert refs[0].label == "[1]"
    assert "World Health Organization" in refs[0].text
    assert refs[1].label == "[2]"
    assert refs[2].label == "[3]"


def test_iter_block_reference_segments_splits_inline_labels() -> None:
    from app.utils.reference_assembler import _iter_block_reference_segments

    segments = _iter_block_reference_segments(
        "cancer screening and diagnosis, Cureus, vol. 14, pp. 1-6, 2022. "
        "[4] A. Esteva, A. Robicquet, B. Ramsundar,"
    )
    assert segments[0][0] is None
    assert "cancer screening" in segments[0][1]
    assert segments[1][0] == 4
    assert segments[1][1].startswith("A. Esteva")


def test_assemble_references_handles_large_sequence() -> None:
    blocks = [
        _processed_block(f"p_b{n}", f"[{n}] Author {n}, Paper {n}, IEEE, 2020.", y0=float(n))
        for n in range(1, 161)
    ]
    refs = assemble_references_from_blocks(blocks, validate=True)
    assert len(refs) == 160
    assert refs[0].label == "[1]"
    assert refs[-1].label == "[160]"


def test_assemble_references_validation_is_optional_during_extraction() -> None:
    blocks = [
        _processed_block("p_b1", "[1] First reference."),
        _processed_block("p_b2", "[3] Third reference."),
    ]
    refs = assemble_references_from_blocks(blocks, validate=False)
    assert len(refs) == 2
    with pytest.raises(ReferenceParsingError):
        assemble_references_from_blocks(blocks, validate=True)


def test_xml_ref_ids_follow_pdf_numbers_not_list_position(tmp_path) -> None:
    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article><front/><body/><back><ref-list><title>References</title></ref-list></back></article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[],
        back={
            "references": [
                MappedSemanticNode(
                    semantic_type="reference",
                    label="[1]",
                    text="[1] World Health Organization. Breast Cancer.",
                    source_block_ids=["p8_b1"],
                ),
                MappedSemanticNode(
                    semantic_type="reference",
                    label="[2]",
                    text="[2] H. Sung, J. Ferlay, vol. 71, pp. 209-249, May 2021.",
                    source_block_ids=["p8_b2"],
                ),
            ]
        },
    )
    xml = generate_jats_xml(template, mapping)
    document = etree.fromstring(xml.encode("utf-8"))
    refs = document.findall(".//ref-list/ref")
    assert refs[0].get("id") == "ref1"
    assert refs[0].findtext("label") == "[1]"
    assert refs[1].get("id") == "ref2"
    assert refs[1].findtext("label") == "[2]"


def test_reference_section_pipeline_keeps_pdf_order_for_wrapped_entries() -> None:
    raw = _raw(
        [
            _page(
                8,
                [
                    _block("p8_b1", "REFERENCES", [50, 100, 150, 115], bold=True),
                    _block("p8_b2", "[1] World Health Organization. Breast Cancer: Prevention and Control.", [50, 130, 550, 145]),
                    _block("p8_b3", "Accessed:Mar.16,2024.[Online].Available:https://www.who.int/news", [50, 146, 550, 161]),
                    _block("p8_b4", "room/fact-sheets/detail/breast-cancer", [50, 162, 550, 177]),
                    _block(
                        "p8_b5",
                        "[2] H. Sung, J. Ferlay, R. L. Siegel, M. Laversanne, I. Soerjomataram, A. Jemal, and F. Bray, "
                        "\u201cGlobal cancer statistics 2020,\u201d CA: Cancer J. Clinicians, vol. 71, no. 3, pp. 209\u2013249, May 2021.",
                        [50, 190, 550, 240],
                    ),
                    _block("p8_b6", "[3] G. Dileep, Another paper, IEEE, 2020.", [50, 250, 550, 270]),
                ],
            )
        ]
    )
    sem = process_document_structure(raw).semantic
    assert sem is not None
    assert len(sem.back.references) == 3
    assert sem.back.references[0].label == "[1]"
    assert "World Health Organization" in sem.back.references[0].text
    assert sem.back.references[1].label == "[2]"
    assert sem.back.references[2].label == "[3]"
