from __future__ import annotations

from app.models.document_structure import ProcessedBlock
from app.services.layout.semantic_builder import _book_paragraph_segments, _book_page_spans_for_blocks
from app.utils.text_utils import split_book_visual_paragraphs


def _block(bid: str, page: int, text: str, y0: float, y1: float) -> ProcessedBlock:
    return ProcessedBlock(
        block_id=bid,
        page_number=page,
        reading_order_index=0,
        column="FULL_WIDTH",
        classification="PARAGRAPH",
        confidence=0.9,
        bbox=[72.0, y0, 400.0, y1],
        text=text,
        block_type="text",
        dominant_font_size=10.0,
    )


def test_split_visual_paragraphs_after_erroneous() -> None:
    blob = (
        "works are pure propaganda without any poetry would also be erroneous. "
        "This text does not contain detailed analysis"
    )
    parts = split_book_visual_paragraphs(blob)
    assert len(parts) >= 2
    assert parts[0].endswith("erroneous.")
    assert parts[1].startswith("This text")


def test_book_paragraph_segments_use_vertical_gap() -> None:
    blocks = [
        _block("a", 8, "First paragraph line one.", 100, 112),
        _block("b", 8, "First paragraph line two.", 112, 124),
        _block("c", 8, "Second paragraph starts here.", 150, 162),
    ]
    segments = _book_paragraph_segments(blocks)
    assert len(segments) == 2
    assert "Second paragraph" in segments[1][1]


def test_chapter_one_splits_arpanet_and_blockquote() -> None:
    blob = (
        "Online organizations espousing social justice (ARPANET). There are similarities between "
        "organizations mystifying these controlled online infrastructures, yet the path leading from "
        "the dotcom boom to the contemporary (2016) global proliferation. In the caption under her "
        "painting of a Kathakali dancer bursting forth through the computer screen, she notes that "
        "One of the best things to happen to India in the nineties was the Computer Revolution. "
        "In this picture the Khathakali dancer represents the Indian computer analyst rising out of "
        "the blue desktop and pouncing on the international scene like a strong and powerful tiger."
    )
    parts = split_book_visual_paragraphs(blob)
    assert len(parts) >= 3
    assert "(ARPANET)." in parts[0]
    assert parts[1].startswith("There are similarities")
    assert parts[1].rstrip().endswith("she notes that")
    assert parts[2].startswith("One of the best things")


def test_blockquote_spans_pages_with_page_spans() -> None:
    blocks = [
        _block(
            "q1",
            3,
            "One of the best things to happen to India in the nineties was the Computer Revolution. "
            "pouncing on the international scene",
            500,
            620,
        ),
        _block("q2", 4, "like a strong and powerful tiger. (Jayaraman Private Collection, 2000)", 80, 120),
    ]
    segments = _book_paragraph_segments(blocks)
    assert len(segments) == 1
    spans = segments[0][2]
    assert len(spans) == 2
    assert spans[0]["page"] == 3
    assert spans[1]["page"] == 4
    assert "international scene" in str(spans[0]["text"])
    assert str(spans[1]["text"]).startswith("like a strong")


def test_chapter_one_layout_paragraph_break_after_arpanet() -> None:
    blocks = [
        _block("a", 3, "First part about ARPANET).", 100, 112),
        _block(
            "b",
            3,
            "There are similarities between organizations mystifying these controlled infrastructures.",
            140,
            200,
        ),
    ]
    segments = _book_paragraph_segments(blocks)
    assert len(segments) == 2


def test_acknowledgments_split_from_single_merged_blob() -> None:
    blob = (
        "As in the case of my previous book this book too was highly collaborative. I thank all my "
        "coauthors. I returned from my faculty improvement leave when I was requested to step in. "
        "get my research and writing done. If I missed thanking anyone my apologies. "
        "I also wish to acknowledge and thank students in my classes. "
        "Finally, I thank Rebecca Lind for agreeing let me reprint chapters which were originally "
        "published as follows:Gajjala, R., Tetteh, D., & Birzescu, A. (2015) Staging the Subaltern Self. "
        "Peter Lang. Gajjala, R., Tetteh, D., & Birzescu, A (2017) Digital Materiality in MATTER."
    )
    parts = split_book_visual_paragraphs(blob)
    assert len(parts) >= 5
    assert parts[0].endswith("writing done.")
    assert parts[1].startswith("If I missed thanking anyone")
    assert any(p.startswith("Gajjala,") for p in parts)


def test_acknowledgments_split_into_multiple_paragraphs() -> None:
    open_para = (
        "As in the case of my previous book Cyberculture and the Subaltern, this book too was "
        "highly collaborative. I thank all my coauthors. I also want to thank the American Culture "
        "Studies secretary for watching for my sanity during the year after I returned from my "
        "faculty improvement"
    )
    cont = (
        "leave when I was requested to step in as Acting Director. Bekka thankyou for reminding me "
        "that being ACS Director did not have to mean that I should not protect some of my time to "
        "get my research and writing done."
    )
    blocks = [
        _block("p1", 7, open_para, 100, 600),
        _block("p2", 8, cont, 80, 200),
        _block("p3", 8, "If I missed thanking anyone\u2014my apologies.", 220, 232),
        _block(
            "p4",
            8,
            "I also wish to acknowledge and thank students in my classes for giving me further insights.",
            250,
            300,
        ),
        _block(
            "p5",
            8,
            "Finally, I thank Rebecca Lind and Stacy Holman for agreeing let me reprint chapters 3 and 4 "
            "which were originally published as follows:",
            320,
            360,
        ),
        _block(
            "p6",
            8,
            "Gajjala, R., Tetteh, D., & Birzescu, A. (2015) Staging the Subaltern Self and the Subaltern Other.",
            380,
            420,
        ),
        _block(
            "p7",
            8,
            "Gajjala, R., Tetteh, D., & Birzescu, A (2017) Digital Materiality in MATTER, Macmillan.",
            440,
            480,
        ),
    ]
    segments = _book_paragraph_segments(blocks)
    texts = [s[1] for s in segments]
    assert len(texts) >= 5
    assert any("faculty improvement" in t and "leave when" in t for t in texts)
    assert any(t.startswith("If I missed thanking anyone") for t in texts)
    assert any("I also wish to acknowledge" in t for t in texts)
    assert any(t.startswith("Finally, I thank Rebecca") for t in texts)
    assert sum(1 for t in texts if t.startswith("Gajjala,")) == 2
    first_spans = segments[0][2]
    assert len(first_spans) >= 2
    assert first_spans[0]["page"] == 7
    assert first_spans[1]["page"] == 8


def test_page_spans_across_pdf_pages() -> None:
    blocks = [
        _block("a", 7, "Reaching a large readership for poetry was", 600, 612),
        _block("b", 8, "a feat in and of itself.", 80, 92),
    ]
    spans = _book_page_spans_for_blocks(blocks)
    assert len(spans) == 2
    assert spans[0]["page"] == 7
    assert spans[1]["page"] == 8
