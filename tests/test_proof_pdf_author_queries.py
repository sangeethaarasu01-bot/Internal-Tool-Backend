"""IEEE proof PDF author-query cover page handling."""

from app.models.document_structure import ProcessedBlock
from app.utils.proof_pdf import (
    apply_author_query_cover_exclusions,
    article_lead_text_from_phase1,
    detect_author_query_cover_pages,
    is_author_queries_page_text,
    is_plausible_author_name,
    is_plausible_journal_title_line,
)

SAMPLE_AQ_PAGE = """
AUTHOR QUERIES
Please note: Author Gateway is now used to process author queries.
Annotate the PDF and return via the gateway. IEEE staff cannot accept new source files.
AQ: 1 Author: please answer the following queries regarding authors.
AQ: 2 Please confirm spelling of author names.
AQ: 3 Corresponding author email is correct.
"""

AMARA_TITLE = "Split Multi-Task Federated Learning for Battery Health and Capacity Estimation"
AMARA_AUTHOR = "Abdelaziz Amara Korba"


def _block(page: int, text: str, block_id: str = "b1") -> ProcessedBlock:
    return ProcessedBlock(
        block_id=block_id,
        page_number=page,
        reading_order_index=0,
        column="FULL_WIDTH",
        classification="PARAGRAPH",
        bbox=[0.0, 0.0, 500.0, 20.0],
        text=text,
        block_type="text",
        dominant_font_size=11.0,
    )


def test_detects_author_queries_cover_page() -> None:
    assert is_author_queries_page_text(SAMPLE_AQ_PAGE)
    pages = detect_author_query_cover_pages(
        [_block(1, SAMPLE_AQ_PAGE), _block(2, f"{AMARA_TITLE}\n{AMARA_AUTHOR}")]
    )
    assert pages == {1}


def test_excludes_cover_blocks_from_content() -> None:
    processed = [
        _block(1, SAMPLE_AQ_PAGE, "aq"),
        _block(2, AMARA_TITLE, "title"),
        _block(2, AMARA_AUTHOR, "author"),
    ]
    from app.models.extraction import DocumentInfo, ExtractionResult, PageExtraction

    raw = ExtractionResult(
        document=DocumentInfo(filename="tce-proof.pdf", page_count=2, requires_ocr=False),
        pages=[
            PageExtraction(
                page_number=1,
                width=600,
                height=800,
                text_char_count=100,
                requires_ocr=False,
                blocks=[],
            ),
            PageExtraction(
                page_number=2,
                width=600,
                height=800,
                text_char_count=100,
                requires_ocr=False,
                blocks=[],
            ),
        ],
    )
    updated = apply_author_query_cover_exclusions(raw, processed)
    assert updated[0].exclude_from_content is True
    assert updated[0].exclusion_reason == "author_queries_cover"
    assert updated[1].exclude_from_content is False


def test_plausible_author_filters_aq_fragments() -> None:
    assert is_plausible_author_name(AMARA_AUTHOR)
    assert not is_plausible_author_name("please answer the following queries")
    assert not is_plausible_author_name("AQ: 1 Author")
    assert not is_plausible_author_name("Annotate the PDF")


def test_plausible_journal_title_rejects_author_queries() -> None:
    assert not is_plausible_journal_title_line("AUTHOR QUERIES")
    assert is_plausible_journal_title_line("IEEE TRANSACTIONS ON INFORMATION THEORY")


def test_article_lead_skips_cover_page() -> None:
    phase1 = {
        "pages": [
            {"raw_page_text": SAMPLE_AQ_PAGE},
            {"raw_page_text": "IEEE TRANSACTIONS ON INFORMATION THEORY\n10.1109/TIT.2026.1\n"},
        ]
    }
    lead = article_lead_text_from_phase1(phase1)
    assert "AUTHOR QUERIES" not in lead
    assert "INFORMATION THEORY" in lead
