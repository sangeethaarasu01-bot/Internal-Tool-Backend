"""Running header/footer exclusion across multi-page layouts."""

from __future__ import annotations

from app.models.extraction import ExtractionResult, PageExtraction, TextBlock, TextLine, TextSpan
from app.services.layout.document_pipeline import process_document_structure
from app.services.layout.text_filter import classify_content_block


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
                spans=[TextSpan(text=text, bbox=bbox, font="Times", size=10.0, flags=0)],
            )
        ],
    )


def _page(page_number: int, blocks: list[TextBlock], height: float = 792.0) -> PageExtraction:
    text = "".join(b.text for b in blocks)
    return PageExtraction(
        page_number=page_number,
        width=612.0,
        height=height,
        text_char_count=len(text),
        requires_ocr=False,
        blocks=blocks,
    )


def _minimal_result(pages: list[PageExtraction]) -> ExtractionResult:
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


def test_roman_folio_and_running_section_title_excluded() -> None:
    body_tail = (
        "thank M. Catherine Smith from Seattle University's School of Theology and"
    )
    body_cont = "Ministry, who provided invaluable assistance in the preparation of the manuscript."
    pages = [
        _page(
            11,
            [
                _block("p11_body", body_tail, [72, 120, 520, 140]),
                _block("p11_folio", "xi", [300, 760, 320, 775]),
            ],
        ),
        _page(
            12,
            [
                _block("p12_hdr", "xii Acknowledgments", [72, 36, 520, 48]),
                _block("p12_body", body_cont, [72, 120, 520, 140]),
            ],
        ),
    ]
    running_headers = {"xii Acknowledgments": {12, 13}}
    for block_id, expected in (("p11_folio", "PAGE_NUMBER"), ("p12_hdr", "RUNNING_HEADER")):
        block = next(b for p in pages for b in p.blocks if b.block_id == block_id)
        page_no = 11 if block_id.startswith("p11") else 12
        decision = classify_content_block(
            block,
            page_no,
            612.0,
            792.0,
            in_references=False,
            running_header_pages=running_headers,
            page_number_candidates={"xi": {11}, "xii": {12}},
            body_font_size=10.0,
            running_footer_pages={"xi": {11, 12}},
        )
        assert decision.exclude_from_content
        assert decision.classification == expected

    body = next(b for p in pages for b in p.blocks if b.block_id == "p12_body")
    body_decision = classify_content_block(
        body,
        12,
        612.0,
        792.0,
        in_references=False,
        running_header_pages=running_headers,
        page_number_candidates={},
        body_font_size=10.0,
    )
    assert body_decision.exclude_from_content is False


def test_book_author_running_header_and_page_numbers_excluded() -> None:
    author_head = "Jane F. Maynard, Mary Clark Moschella, and Leonard Hummel"
    body1 = (
        "tradition, while not a cultural consensus that binds all into one, "
        "is an organizing principle that influences some of the beliefs"
    )
    body2 = "and practices of many."
    pages = [
        _page(
            1,
            [
                _block("p1_body", body1, [72, 120, 520, 200]),
                _block("p1_folio", "1", [300, 755, 320, 770]),
            ],
        ),
        _page(
            2,
            [
                _block("p2_hdr", f"2 {author_head}", [48, 40, 520, 52]),
                _block("p2_body", body2, [72, 120, 520, 160]),
            ],
        ),
        _page(
            3,
            [
                _block("p3_hdr", f"3 {author_head}", [48, 40, 520, 52]),
                _block("p3_body", "How do the members of an Episcopal congregation respond?", [72, 120, 520, 160]),
            ],
        ),
    ]
    structure = process_document_structure(_minimal_result(pages), include_tagged_output=False)
    included = " ".join((b.text or "") for b in structure.blocks if not b.exclude_from_content)
    assert author_head not in included
    assert "Episcopal congregation" in included
    assert not any(
        (b.text or "").strip() == "1" and not b.exclude_from_content for b in structure.blocks
    )
    assert "organizing principle" in included
    assert all(b.exclude_from_content for b in structure.blocks if (b.text or "").strip() in {"1", "xi"})
    assert all(
        b.exclude_from_content
        for b in structure.blocks
        if author_head in (b.text or "")
    )


def test_roman_footer_xi_excluded() -> None:
    pages = [
        _page(
            11,
            [
                _block("p11_body", "multiplicity and messiness of lived religion is startlingly revealed.", [72, 120, 520, 200]),
                _block("p11_folio", "xi", [300, 755, 320, 770]),
            ],
        ),
        _page(
            12,
            [
                _block("p12_folio", "xii", [300, 755, 320, 770]),
                _block("p12_body", "At the same time, it reveals that tradition endures.", [72, 120, 520, 160]),
            ],
        ),
    ]
    structure = process_document_structure(_minimal_result(pages), include_tagged_output=False)
    assert all(
        b.exclude_from_content
        for b in structure.blocks
        if (b.text or "").strip().lower() in {"xi", "xii"}
    )


def test_pipeline_omits_running_furniture_from_semantic_body() -> None:
    abstract = "Abstract—This study presents a novel diagnostic approach for battery systems."
    body_p1 = "The rapid adoption of electric vehicles has changed battery diagnostics."
    body_p2 = "Experimental results confirm the proposed method on a large fleet dataset."
    pages = [
        _page(
            1,
            [
                _block("p1_title", "Battery Diagnostics in Modern EVs", [72, 90, 500, 110]),
                _block("p1_abs", abstract, [72, 130, 520, 180]),
                _block("p1_body", body_p1, [72, 200, 520, 260]),
            ],
        ),
        _page(
            2,
            [
                _block("p2_hdr", "IEEE TRANSACTIONS ON VEHICULAR TECHNOLOGY", [72, 30, 520, 42]),
                _block("p2_body", body_p2, [72, 120, 520, 180]),
                _block("p2_num", "2", [300, 760, 320, 775]),
            ],
        ),
        _page(
            3,
            [
                _block("p3_hdr", "IEEE TRANSACTIONS ON VEHICULAR TECHNOLOGY", [72, 30, 520, 42]),
                _block("p3_body", "Conclusions summarize the contributions of this work.", [72, 120, 520, 160]),
                _block("p3_num", "3", [300, 760, 320, 775]),
            ],
        ),
    ]
    structure = process_document_structure(_minimal_result(pages), include_tagged_output=False)
    included = " ".join(
        (b.text or "") for b in structure.blocks if not b.exclude_from_content
    )
    assert "IEEE TRANSACTIONS ON VEHICULAR TECHNOLOGY" not in included
    assert "Experimental results confirm" in included
    assert "Conclusions summarize" in included
    assert all(
        b.exclude_from_content
        for b in structure.blocks
        if "IEEE TRANSACTIONS" in (b.text or "")
    )
    assert "novel diagnostic" in included
