from __future__ import annotations

from app.models.extraction import DocumentInfo, ExtractionResult, ExtractionStats, PageExtraction, TextBlock, TextLine, TextSpan
from app.services.layout.book_page_folios import build_book_page_folio_map, folio_label_for_pdf_page


def _margin_block(block_id: str, page: int, text: str, y0: float) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        type="text",
        bbox=[50.0, y0, 400.0, y0 + 12.0],
        text=text,
        lines=[
            TextLine(
                line_id=f"{block_id}_l0",
                bbox=[50.0, y0, 400.0, y0 + 12.0],
                text=text,
                spans=[TextSpan(text=text, bbox=[50.0, y0, 400.0, y0 + 12.0], font="Times", size=9.0, flags=0)],
            )
        ],
    )


def test_build_book_page_folio_map_roman_and_arabic() -> None:
    pages = [
        PageExtraction(
            page_number=4,
            width=432.0,
            height=648.0,
            text_char_count=2,
            requires_ocr=False,
            blocks=[_margin_block("p4_b0", 4, "iv", 20.0)],
        ),
        PageExtraction(
            page_number=12,
            width=432.0,
            height=648.0,
            text_char_count=2,
            requires_ocr=False,
            blocks=[_margin_block("p12_b0", 12, "8", 630.0)],
        ),
    ]
    raw = ExtractionResult(
        document=DocumentInfo(filename="t.pdf", page_count=2, requires_ocr=False),
        pages=pages,
        stats=ExtractionStats(total_chars=4),
    )
    folios = build_book_page_folio_map(raw)
    assert folios["4"] == "iv"
    assert folios["12"] == "8"
    assert folio_label_for_pdf_page(folios, 4) == "iv"
