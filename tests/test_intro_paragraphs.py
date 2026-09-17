"""Integration tests for Introduction multi-paragraph extraction."""

from __future__ import annotations

from app.models.extraction import PageExtraction, TextBlock, TextLine, TextSpan
from app.services.layout.document_pipeline import process_document_structure
from app.models.extraction import DocumentInfo, ExtractionResult, ExtractionStats


def _span(text: str, bbox: list[float]) -> TextSpan:
    return TextSpan(text=text, bbox=bbox, font="Helvetica", size=10.0, flags=0)


def _line(text: str, bbox: list[float]) -> TextLine:
    return TextLine(line_id="l0", bbox=bbox, text=text, spans=[_span(text, bbox)])


def _block(block_id: str, text: str, bbox: list[float], column_x: float = 50.0) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        type="text",
        bbox=bbox,
        text=text,
        lines=[_line(text, bbox)],
    )


def _page(page_number: int, blocks: list[TextBlock]) -> PageExtraction:
    text = "".join(block.text for block in blocks)
    return PageExtraction(
        page_number=page_number,
        width=600,
        height=800,
        text_char_count=len(text),
        requires_ocr=False,
        blocks=blocks,
    )


def _raw(pages: list[PageExtraction]) -> ExtractionResult:
    return ExtractionResult(
        document=DocumentInfo(filename="test.pdf", page_count=len(pages), requires_ocr=False),
        pages=pages,
        stats=ExtractionStats(
            total_blocks=sum(len(page.blocks) for page in pages),
            total_lines=sum(len(block.lines) for page in pages for block in page.blocks),
            total_chars=sum(page.text_char_count for page in pages),
        ),
    )


def test_introduction_keeps_tf_and_observed_paragraphs() -> None:
    blocks = [
        _block("p2_b1", "I. INTRODUCTION", [49, 80, 160, 95]),
        _block("p2_b2", "RESEARCHERS have been seeking alternative instrumental means.", [50, 110, 280, 125]),
        _block(
            "p2_b3",
            "Human tea tasting is completely subjective and suffers from inconsistency.",
            [320, 110, 560, 125],
        ),
        _block("p2_b4", "TF, TAN, and TH belong to the group of flavonoids,", [50, 140, 280, 155]),
        _block("p2_b5", "each of", [50, 156, 120, 170]),
        _block(
            "p2_b6",
            "these groups and their derivatives is known to influence the taste of tea significantly.",
            [50, 171, 280, 200],
        ),
        _block(
            "p2_b7",
            "It was observed that multimolecular sensing using a single sensor was hazardous.",
            [50, 220, 280, 250],
        ),
        _block(
            "p2_b8",
            "The novelty of this approach lies in the development of a customized e-tongue.",
            [320, 220, 560, 250],
        ),
    ]
    structure = process_document_structure(_raw([_page(2, blocks)]))
    sem = structure.semantic
    assert sem is not None
    intro = sem.body.sections[0]
    paragraph_text = " ".join(node.text for node in intro.content if node.type == "paragraph")
    assert "Human tea tasting" in paragraph_text
    assert "TF, TAN, and TH belong" in paragraph_text
    assert "these groups and their derivatives" in paragraph_text
    assert "It was observed that multimolecular sensing" in paragraph_text
    assert "The novelty of this approach lies" in paragraph_text
    assert paragraph_text.count("Human tea tasting") == 1
