from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.models.extraction import ExtractionResult, PageExtraction, TextBlock, TextLine, TextSpan
from app.services.layout.column_classifier import classify_column
from app.services.layout.document_pipeline import process_document_structure
from app.services.layout.reading_order import order_page_blocks
from app.services.layout.text_filter import classify_content_block
from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
IEEE_PDF = ROOT / "uploads" / "20260907_132003_jsen-banerjeeroy-3639180-proof1.pdf"


def _block(block_id: str, text: str, bbox: list[float]) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        type="text",
        bbox=bbox,
        text=text,
        lines=[
            TextLine(
                line_id=f"{block_id}_l0",
                bbox=bbox,
                text=text,
                spans=[TextSpan(text=text, bbox=bbox, font="Helvetica", size=10.0, flags=0)],
            )
        ],
    )


def _page(page_number: int, blocks: list[TextBlock], width: float = 600.0, height: float = 800.0):
    text = "".join(block.text for block in blocks)
    return PageExtraction(
        page_number=page_number,
        width=width,
        height=height,
        text_char_count=len(text),
        requires_ocr=False,
        blocks=blocks,
    )


def _result(pages: list[PageExtraction]) -> ExtractionResult:
    from app.models.extraction import DocumentInfo, ExtractionStats

    return ExtractionResult(
        document=DocumentInfo(filename="test.pdf", page_count=len(pages), requires_ocr=False),
        pages=pages,
        stats=ExtractionStats(
            total_blocks=sum(len(p.blocks) for p in pages),
            total_lines=sum(len(b.lines) for p in pages for b in p.blocks),
            total_chars=sum(p.text_char_count for p in pages),
        ),
    )


def test_column_classification_two_column() -> None:
    assert classify_column([50, 100, 250, 200], 600) == "LEFT"
    assert classify_column([320, 100, 550, 200], 600) == "RIGHT"
    assert classify_column([50, 100, 550, 200], 600) == "FULL_WIDTH"


def test_reading_order_left_before_right() -> None:
    page = _page(
        1,
        [
            _block("p1_b0", "header", [50, 20, 550, 30]),
            _block("p1_b1", "left top", [50, 100, 250, 120]),
            _block("p1_b2", "right top", [320, 100, 550, 120]),
            _block("p1_b3", "left bottom", [50, 500, 250, 520]),
        ],
    )
    ordered = order_page_blocks(page)
    ids = [b.block_id for b in ordered]
    assert ids.index("p1_b0") < ids.index("p1_b1")
    assert ids.index("p1_b1") < ids.index("p1_b3")
    assert ids.index("p1_b3") < ids.index("p1_b2")


def test_reference_near_bottom_not_footer(tmp_path: Path) -> None:
    page = _page(
        7,
        [
            _block(
                "p7_b19",
                "sitive determination of gallic acid in green tea, IEEE Sensors J., vol. 21, "
                "no. 5, pp. 5687-5694, doi: 10.1109/JSEN.2020.3036663.",
                [67, 743, 300, 760],
            )
        ],
        width=612,
        height=792,
    )
    decision = classify_content_block(
        page.blocks[0],
        7,
        page.width,
        page.height,
        in_references=True,
        running_header_pages={},
        page_number_candidates={},
        body_font_size=10.0,
    )
    assert decision.classification == "REFERENCE_TEXT"
    assert decision.exclude_from_content is False


def test_ieee_access_margin_boilerplate_excluded() -> None:
    received = (
        "Received 13 November 2025, accepted 24 November 2025. "
        "Date of publication 00 xxxx 0000, date of current version 00 xxxx 0000."
    )
    license_line = (
        "2025 The Authors. This work is licensed under a Creative Commons Attribution 4.0 License."
    )
    page = _page(
        2,
        [
            _block("p2_top", "D", [50, 25, 60, 40]),
            _block("p2_vol", "VOLUME 13, 2025", [200, 25, 400, 40]),
            _block("p2_body", "Main article paragraph on page two.", [50, 120, 520, 200]),
            _block("p2_num", "2", [300, 760, 320, 775]),
            _block("p2_cc", license_line, [50, 743, 520, 770]),
            _block("p2_hist", received, [50, 60, 520, 90]),
        ],
        width=612,
        height=792,
    )
    for block_id, expected in (
        ("p2_top", "RUNNING_HEADER"),
        ("p2_vol", "RUNNING_HEADER"),
        ("p2_num", "PAGE_NUMBER"),
        ("p2_cc", "FOOTER"),
        ("p2_hist", "RUNNING_HEADER"),
    ):
        block = next(b for b in page.blocks if b.block_id == block_id)
        decision = classify_content_block(
            block,
            2,
            page.width,
            page.height,
            in_references=False,
            running_header_pages={},
            page_number_candidates={"2": {2}},
            body_font_size=10.0,
        )
        assert decision.exclude_from_content is True
        assert decision.classification == expected

    body = next(b for b in page.blocks if b.block_id == "p2_body")
    body_decision = classify_content_block(
        body,
        2,
        page.width,
        page.height,
        in_references=False,
        running_header_pages={},
        page_number_candidates={},
        body_font_size=10.0,
    )
    assert body_decision.exclude_from_content is False


def test_copyright_footer_excluded() -> None:
    page = _page(
        1,
        [
            _block(
                "p1_b16",
                "1558-1748 © 2025 IEEE. All rights reserved, including rights for text and data mining.",
                [90, 743, 520, 760],
            )
        ],
        width=612,
        height=792,
    )
    decision = classify_content_block(
        page.blocks[0],
        1,
        page.width,
        page.height,
        in_references=False,
        running_header_pages={},
        page_number_candidates={},
        body_font_size=10.0,
    )
    assert decision.classification == "FOOTER"
    assert decision.exclude_from_content is True


def test_page_start_paragraph_not_section() -> None:
    page = _page(
        2,
        [
            _block(
                "p2_b1",
                "the proposed architecture consists of multiple sensor nodes and a switching circuit",
                [50, 80, 280, 140],
            )
        ],
    )
    decision = classify_content_block(
        page.blocks[0],
        2,
        page.width,
        page.height,
        in_references=False,
        running_header_pages={},
        page_number_candidates={},
        body_font_size=10.0,
    )
    assert decision.classification in {"PARAGRAPH", "BODY_TEXT"}
    assert decision.classification != "SECTION"


def test_section_heading_detected() -> None:
    page = _page(
        1,
        [
            TextBlock(
                block_id="p1_h1",
                type="text",
                bbox=[50, 200, 550, 220],
                text="I. INTRODUCTION",
                lines=[
                    TextLine(
                        line_id="p1_h1_l0",
                        bbox=[50, 200, 550, 220],
                        text="I. INTRODUCTION",
                        spans=[
                            TextSpan(
                                text="I. INTRODUCTION",
                                bbox=[50, 200, 550, 220],
                                font="Helvetica-Bold",
                                size=12.0,
                                flags=2,
                            )
                        ],
                    )
                ],
            )
        ],
        width=612,
    )
    decision = classify_content_block(
        page.blocks[0],
        1,
        page.width,
        page.height,
        in_references=False,
        running_header_pages={},
        page_number_candidates={},
        body_font_size=10.0,
    )
    assert decision.classification in {"SECTION", "SUBSECTION"}


def test_section_content_continues_across_pages() -> None:
    raw = _result(
        [
            _page(
                1,
                [
                    TextBlock(
                        block_id="p1_s1",
                        type="text",
                        bbox=[50, 200, 550, 220],
                        text="III. METHODOLOGY",
                        lines=[
                            TextLine(
                                line_id="p1_s1_l0",
                                bbox=[50, 200, 550, 220],
                                text="III. METHODOLOGY",
                                spans=[
                                    TextSpan(
                                        text="III. METHODOLOGY",
                                        bbox=[50, 200, 550, 220],
                                        font="Helvetica-Bold",
                                        size=12.0,
                                        flags=2,
                                    )
                                ],
                            )
                        ],
                    ),
                    _block("p1_p1", "Paragraph on page 1 continues", [50, 240, 280, 760]),
                ],
            ),
            _page(
                2,
                [
                    _block(
                        "p2_p1",
                        "and continues naturally at the top of page 2 without a new section.",
                        [50, 80, 280, 140],
                    )
                ],
            ),
        ]
    )
    structure = process_document_structure(raw)
    assert structure.structure_stats.detected_sections >= 1
    section = structure.sections[0]
    assert len(section.items) >= 2
    assert section.content_source_block_ids == ["p1_p1", "p2_p1"]


def test_completeness_report_tracks_exclusions() -> None:
    raw = _result(
        [
            _page(
                1,
                [
                    _block("p1_b1", "Meaningful body text for completeness.", [50, 200, 280, 240]),
                    _block(
                        "p1_b2",
                        "© 2025 IEEE. All rights reserved.",
                        [90, 743, 520, 760],
                    ),
                ],
                width=612,
                height=792,
            )
        ]
    )
    structure = process_document_structure(raw)
    assert structure.completeness.raw_char_count > 0
    assert structure.completeness.excluded_char_count > 0
    assert structure.completeness.retained_char_count > 0
    assert any(item.classification == "FOOTER" for item in structure.completeness.excluded_blocks)


def test_unknown_text_retained_not_dropped() -> None:
    raw = _result([_page(1, [_block("p1_x", "???", [50, 400, 80, 420])])])
    structure = process_document_structure(raw)
    retained_ids = {
        b.block_id for b in structure.blocks if not b.exclude_from_content
    }
    assert "p1_x" in retained_ids


def test_empty_page(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf)
    doc.close()
    raw = extract_text_layout(str(pdf))
    structure = process_document_structure(raw)
    assert structure.completeness.raw_char_count == 0


@pytest.mark.skipif(not IEEE_PDF.exists(), reason="IEEE proof PDF not in uploads")
def test_ieee_pdf_reference_not_footer() -> None:
    raw = extract_text_layout(str(IEEE_PDF))
    structure = process_document_structure(raw)
    p7_b19 = next(b for b in structure.blocks if b.block_id == "p7_b19")
    assert p7_b19.classification == "REFERENCE_TEXT"
    assert p7_b19.exclude_from_content is False


@pytest.mark.skipif(not IEEE_PDF.exists(), reason="IEEE proof PDF not in uploads")
def test_ieee_pdf_running_headers_excluded() -> None:
    raw = extract_text_layout(str(IEEE_PDF))
    structure = process_document_structure(raw)
    p2_b0 = next(b for b in structure.blocks if b.block_id == "p2_b0")
    assert p2_b0.classification == "RUNNING_HEADER"
    assert p2_b0.exclude_from_content is True


@pytest.mark.skipif(not IEEE_PDF.exists(), reason="IEEE proof PDF not in uploads")
def test_ieee_pdf_no_silent_text_loss() -> None:
    raw = extract_text_layout(str(IEEE_PDF))
    structure = process_document_structure(raw)
    accounted = structure.completeness.retained_char_count + structure.completeness.excluded_char_count
    assert accounted >= structure.completeness.raw_char_count * 0.95
