from __future__ import annotations

from pathlib import Path

import pytest

from app.models.extraction import ExtractedTable, ExtractionResult, PageExtraction, TextBlock, TextLine, TextSpan
from app.services.layout.document_pipeline import process_document_structure
from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
IEEE_PDF = ROOT / "uploads" / "20260907_132003_jsen-banerjeeroy-3639180-proof1.pdf"


def _span(text: str, size: float, bold: bool = False, bbox: list[float] | None = None) -> TextSpan:
    bb = bbox or [50, 100, 300, 120]
    return TextSpan(text=text, bbox=bb, font="Helvetica-Bold" if bold else "Helvetica", size=size, flags=2 if bold else 0)


def _block(block_id: str, text: str, bbox: list[float], size: float = 10.0, bold: bool = False) -> TextBlock:
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
                spans=[_span(text, size, bold=bold, bbox=bbox)],
            )
        ],
    )


def _page(page_number: int, blocks: list[TextBlock], width: float = 612.0, height: float = 792.0) -> PageExtraction:
    text = "".join(b.text for b in blocks)
    return PageExtraction(
        page_number=page_number,
        width=width,
        height=height,
        text_char_count=len(text),
        requires_ocr=False,
        blocks=blocks,
    )


def _raw(pages: list[PageExtraction]) -> ExtractionResult:
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


def test_title_merges_multiple_blocks() -> None:
    raw = _raw(
        [
            _page(
                1,
                [
                    _block("p1_b1", "A Customized Electronic Tongue by Developing", [55, 68, 556, 90], size=24),
                    _block("p1_b2", "Voltammetric Electrodes for Tea", [138, 124, 474, 148], size=24),
                    _block("p1_b3", "Quality Evaluation", [210, 152, 402, 176], size=24),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    assert structure.semantic is not None
    title = structure.semantic.front.title
    assert title is not None
    assert len(title.source_block_ids) == 3
    assert "Quality Evaluation" in title.text
    assert "<article-title" in structure.semantic.tagged_output


def test_authors_not_paragraph_tags() -> None:
    raw = _raw(
        [
            _page(
                1,
                [
                    _block("p1_b4", "Madhurima Moulick, Sagar Chowdhury, Member, IEEE,", [60, 193, 556, 205], size=11),
                    _block("p1_b5", "Jeet Naskar, and Runu Banerjee Roy", [168, 206, 402, 218], size=11),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    assert structure.semantic is not None
    assert len(structure.semantic.front.authors) >= 3
    assert all(author.tag == "contrib" for author in structure.semantic.front.authors)
    author_text = " ".join(author.text for author in structure.semantic.front.authors)
    assert "Runu Banerjee Roy" in author_text
    assert "Madhurima Moulick" in author_text


def test_abstract_and_keywords_semantic_tags() -> None:
    raw = _raw(
        [
            _page(
                1,
                [
                    _block(
                        "p1_b7",
                        "Abstract—In this facile approach, a well-developed voltammetric electronic tongue.",
                        [50, 260, 300, 320],
                        size=9,
                        bold=True,
                    ),
                    _block(
                        "p1_b8",
                        "Index Terms— Electronic tongue, total theaflavins, voltammograms",
                        [50, 486, 300, 510],
                        size=9,
                        bold=True,
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert sem.front.abstract is not None
    assert sem.front.abstract.tag == "abstract"
    assert sem.front.keywords is not None
    assert sem.front.keywords.tag == "kwd-group"
    assert len(sem.front.keywords.keywords) >= 2


def test_section_heading_not_generic_paragraph() -> None:
    raw = _raw(
        [
            _page(
                1,
                [
                    TextBlock(
                        block_id="p1_b9",
                        type="text",
                        bbox=[49, 534, 120, 548],
                        text="I. INTRODUCTION",
                        lines=[
                            TextLine(
                                line_id="p1_b9_l0",
                                bbox=[49, 534, 120, 548],
                                text="I. INTRODUCTION",
                                spans=[_span("I. INTRODUCTION", 10, bold=True, bbox=[49, 534, 120, 548])],
                            )
                        ],
                    ),
                    _block(
                        "p1_b10",
                        "RESEARCHERS have been seeking alternative instrumental means for a long time.",
                        [71, 552, 300, 600],
                        size=10,
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert len(sem.body.sections) >= 1
    assert sem.body.sections[0].heading == "INTRODUCTION"
    assert sem.body.sections[0].heading_element.label == "I."
    assert "<sec" in sem.tagged_output
    assert "<label" in sem.tagged_output
    assert ">I.</label>" in sem.tagged_output
    assert "<title" in sem.tagged_output
    assert ">INTRODUCTION</title>" in sem.tagged_output


def test_no_page_section_tags() -> None:
    raw = _raw([_page(1, [_block("p1_b1", "Sample body text for page one.", [50, 200, 280, 240])])])
    structure = process_document_structure(raw)
    assert structure.semantic is not None
    assert 'class="page-1"' not in structure.semantic.tagged_output
    assert "<page " not in structure.semantic.tagged_output


def test_subsection_headings_detected() -> None:
    raw = _raw(
        [
            _page(
                3,
                [
                    _block("p3_b6", "E. e-Tongue Setup", [50, 300, 200, 312], size=10, bold=True),
                    _block("p3_b7", "An e-tongue set up has been designed using an array.", [50, 320, 280, 400]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert any(
        sub.heading == "e-Tongue Setup" and sub.heading_element.label == "E."
        for sec in sem.body.sections
        for sub in sec.subsections
    ) or any(sec.heading == "e-Tongue Setup" and sec.heading_element.label == "E." for sec in sem.body.sections)


def test_list_item_not_section() -> None:
    raw = _raw(
        [
            _page(
                4,
                [
                    _block(
                        "p4_b4",
                        "2) Timing Signal Generator: An ATmega328p-based micro-controller has been utilized.",
                        [50, 380, 280, 450],
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    tagged = sem.tagged_output
    assert "list-item" in tagged
    assert 'list-type="order"' in tagged
    assert "Timing Signal Generator" in tagged
    assert "data-list-marker=\"2)\"" in tagged
    assert "2) Timing Signal Generator" not in tagged.split("<p")[1] if "<p" in tagged else True


def _find_lists(sem) -> list:
    lists = []

    def walk_sections(sections):
        for sec in sections:
            for item in sec.content:
                if item.type == "list":
                    lists.append(item)
            walk_sections(sec.subsections)

    walk_sections(sem.body.sections)
    for item in sem.body.loose_paragraphs:
        if item.type == "list":
            lists.append(item)
    return lists


def test_ordered_list_grouping_numeric() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block("p2_b1", "1. Local Accuracy: This ensures local fidelity.", [50, 100, 280, 115]),
                    _block("p2_b2", "2. Missingness: This handles missing features.", [50, 120, 280, 135]),
                    _block("p2_b3", "3. Consistency: Values remain consistent.", [50, 140, 280, 155]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert lists[0].list_type == "order"
    assert len(lists[0].children) == 3
    assert lists[0].children[0].text.startswith("Local Accuracy")
    assert lists[0].children[1].text.startswith("Missingness")
    assert lists[0].children[2].text.startswith("Consistency")


def test_bullet_list_grouping() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block("p2_b1", "• First item with explanatory text.", [50, 100, 280, 115]),
                    _block("p2_b2", "• Second item with more detail.", [50, 120, 280, 135]),
                    _block("p2_b3", "• Third item closes the list.", [50, 140, 280, 155]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert lists[0].list_type == "bullet"
    assert len(lists[0].children) == 3


def test_alphabetic_ordered_list() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block("p2_b1", "a) First alpha item.", [50, 100, 280, 115]),
                    _block("p2_b2", "b) Second alpha item.", [50, 120, 280, 135]),
                    _block("p2_b3", "c) Third alpha item.", [50, 140, 280, 155]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert lists[0].list_type == "order"
    assert len(lists[0].children) == 3


def test_roman_ordered_list() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block("p2_b1", "i. First roman item.", [50, 100, 280, 115]),
                    _block("p2_b2", "ii. Second roman item.", [50, 120, 280, 135]),
                    _block("p2_b3", "iii. Third roman item.", [50, 140, 280, 155]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert lists[0].list_type == "order"
    assert len(lists[0].children) == 3


def test_wrapped_list_item_merged() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block(
                        "p2_b1",
                        "1. Local Accuracy: This ensures that the explanation",
                        [50, 100, 280, 115],
                    ),
                    _block(
                        "p2_b2",
                        "model output continues on next line for the same item.",
                        [72, 116, 280, 131],
                    ),
                    _block("p2_b3", "2. Missingness: A separate list item.", [50, 140, 280, 155]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert len(lists[0].children) == 2
    assert "model output continues" in lists[0].children[0].text
    assert "Missingness" in lists[0].children[1].text


def test_heading_not_list_for_section() -> None:
    raw = _raw(
        [
            _page(
                4,
                [
                    _block("p4_b14", "III. RESULTS AND DISCUSSIONS", [320, 460, 520, 475], bold=True),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert lists == []
    assert any(sec.heading == "RESULTS AND DISCUSSIONS" and sec.heading_element.label == "III." for sec in sem.body.sections)


def test_subsection_not_list() -> None:
    raw = _raw(
        [
            _page(
                3,
                [
                    _block("p3_b6", "F. Response Recording From e-Tongue", [50, 300, 280, 312], size=10, bold=True),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert lists == []
    tagged = sem.tagged_output
    assert ">F.</label>" in tagged
    assert "Response Recording From e-Tongue" in tagged


def test_multiline_block_splits_into_multiple_items() -> None:
    raw = _raw(
        [
            _page(
                5,
                [
                    _block(
                        "p5_b13",
                        "1) Fused data: 50 to 180.\n2) Total of samples: 50 (5 Samples x Runs: 10).\n3) No. of features: 180 (TAN: 60+TF: 60+TH: 60) (Com-\nbination of TAN [TAN_0, TAN_1]).",
                        [50, 500, 280, 560],
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert lists[0].list_type == "order"
    assert len(lists[0].children) == 3
    assert "Fused data" in lists[0].children[0].text
    assert "Total of samples" in lists[0].children[1].text
    assert "bination of TAN" in lists[0].children[2].text
    assert "Com-" not in lists[0].children[2].text


def test_breast_cancer_objectives_list_preserves_all_blocks() -> None:
    blocks = [
        _block(
            "p2_b10",
            "1. To identify, collect, and synthesize existing research on",
            [321, 452, 556, 470],
        ),
        _block(
            "p2_b11",
            "the application of XAI techniques in the detection and",
            [321, 472, 556, 490],
        ),
        _block("p2_b12", "diagnosis of breast cancer.", [321, 492, 556, 510]),
        _block(
            "p2_b13",
            "2. To assess various XAI approaches, including both",
            [321, 512, 556, 530],
        ),
        _block(
            "p2_b14",
            "model-agnostic and model-specific techniques, in terms",
            [321, 532, 556, 550],
        ),
        _block(
            "p2_b15",
            "of their effectiveness in improving the transparency and",
            [321, 552, 556, 570],
        ),
        _block(
            "p2_b16",
            "diagnostic accuracy of ML and DL models used for",
            [321, 572, 556, 590],
        ),
        _block("p2_b17", "breast cancer detection.", [321, 592, 556, 610]),
        _block(
            "p2_b18",
            "3. To explore the obstacles faced in integrating XAI",
            [321, 612, 556, 630],
        ),
        _block(
            "p2_b19",
            "technologies into clinical workflows for breast cancer",
            [321, 632, 556, 650],
        ),
        _block(
            "p2_b20",
            "diagnosis and to emphasize the importance of developing",
            [321, 652, 556, 670],
        ),
        _block(
            "p2_b21",
            "standardized metrics for evaluating the performance",
            [321, 672, 556, 690],
        ),
        _block("p2_b22", "and effectiveness of XAI models.", [321, 692, 556, 710]),
    ]
    raw = _raw([_page(2, blocks)])
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert len(lists[0].children) == 3

    item1, item2, item3 = lists[0].children
    assert item1.list_marker == "1."
    assert item1.source_block_ids == ["p2_b10", "p2_b11", "p2_b12"]
    assert "diagnosis of breast cancer." in item1.text
    assert item1.bbox == [321, 452, 556, 510]

    assert item2.list_marker == "2."
    assert item2.source_block_ids == ["p2_b13", "p2_b14", "p2_b15", "p2_b16", "p2_b17"]
    assert "breast cancer detection." in item2.text

    assert item3.list_marker == "3."
    assert item3.source_block_ids == [
        "p2_b18",
        "p2_b19",
        "p2_b20",
        "p2_b21",
        "p2_b22",
    ]
    assert "effectiveness of XAI models." in item3.text


def test_bullet_list_preserves_wrapped_blocks() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block("p2_b1", "• Breast cancer detection using XAI", [50, 100, 280, 115]),
                    _block("p2_b2", "techniques improves transparency.", [72, 116, 280, 131]),
                    _block("p2_b3", "• Model-specific methods provide", [50, 140, 280, 155]),
                    _block("p2_b4", "interpretable predictions.", [72, 156, 280, 171]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert lists[0].list_type == "bullet"
    assert len(lists[0].children) == 2
    assert lists[0].children[0].source_block_ids == ["p2_b1", "p2_b2"]
    assert "techniques improves transparency." in lists[0].children[0].text
    assert lists[0].children[1].source_block_ids == ["p2_b3", "p2_b4"]
    assert "interpretable predictions." in lists[0].children[1].text


def test_list_item_continues_across_page_break() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block("p2_b1", "1. Objective starts on page two and continues", [50, 700, 280, 715]),
                ],
            ),
            _page(
                3,
                [
                    _block("p3_b1", "with wrapped content on the next page.", [50, 80, 280, 95]),
                    _block("p3_b2", "2. Second objective begins here.", [50, 110, 280, 125]),
                ],
            ),
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert len(lists[0].children) == 2
    assert lists[0].children[0].source_block_ids == ["p2_b1", "p3_b1"]
    assert "next page." in lists[0].children[0].text


def test_list_does_not_absorb_following_paragraph() -> None:
    objectives = (
        "1) To identify, collect, and synthesize existing research on the application of "
        "XAI techniques in the detection and diagnosis of breast cancer.\n"
        "2) To assess various XAI approaches, including both model-agnostic and model-specific "
        "techniques, in terms of their effectiveness in improving the transparency and "
        "diagnostic accuracy of ML and DL models used for breast cancer detection.\n"
        "3) To explore the obstacles faced in integrating XAI technologies into clinical "
        "workflows for breast cancer diagnosis and to emphasize the importance of developing "
        "standardized metrics for evaluating the performance and effectiveness of XAI models.\n"
        "The study will also investigate how XAI techniques can enhance trust in automated "
        "detection systems among healthcare professionals and patients."
    )
    raw = _raw([_page(2, [_block("p2_b10", objectives, [321, 452, 556, 710])])])
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert len(lists[0].children) == 3
    assert "effectiveness of XAI models." in lists[0].children[2].text
    assert "The study will also investigate" not in lists[0].children[2].text
    assert any(
        "The study will also investigate" in element.text
        for element in sem.body.loose_paragraphs
    )


def test_list_does_not_absorb_following_paragraph_separate_block() -> None:
    raw = _raw(
        [
            _page(
                2,
                [
                    _block(
                        "p2_b10",
                        "1) First objective about breast cancer research.\n"
                        "2) Second objective about model transparency.\n"
                        "3) Third objective about clinical workflow integration and XAI models.",
                        [321, 452, 556, 650],
                    ),
                    _block(
                        "p2_b11",
                        "The study will also investigate how XAI techniques can enhance trust "
                        "in automated detection systems among healthcare professionals and patients.",
                        [321, 660, 556, 710],
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    lists = _find_lists(sem)
    assert len(lists) == 1
    assert len(lists[0].children) == 3
    assert "The study will also investigate" not in lists[0].children[2].text
    assert lists[0].source_block_ids == ["p2_b10"]
    assert any(
        "The study will also investigate" in element.text
        for element in sem.body.loose_paragraphs
    )


def test_equation_grouping() -> None:
    raw = _raw(
        [
            _page(
                6,
                [
                    _block("p6_b42", "yHPLC", [50, 400, 80, 415], size=8, bold=True),
                    _block("p6_b43", "TAN = fTAN(XTAN)", [50, 416, 180, 430], size=8, bold=True),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert "disp-formula" in sem.tagged_output
    assert "fTAN" in sem.tagged_output
    assert "<label" in sem.tagged_output
    assert ">(1)</label>" in sem.tagged_output


def test_thin_line_not_figure() -> None:
    from app.models.extraction import TextBlock

    raw = _raw(
        [
            PageExtraction(
                page_number=6,
                width=612,
                height=792,
                text_char_count=0,
                requires_ocr=False,
                blocks=[
                    TextBlock(
                        block_id="p6_b2",
                        type="image",
                        bbox=[49, 148, 562, 149],
                        text="",
                        lines=[],
                    )
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert "layout-object" in sem.tagged_output or len(sem.unknown) == 0


def test_section_hierarchy_roman_and_letter() -> None:
    raw = _raw(
        [
            _page(4, [_block("p4_b14", "III. RESULTS AND DISCUSSIONS", [320, 460, 520, 475], bold=True)]),
            _page(
                5,
                [
                    _block("p5_b6", "B. Clustering Using t-SNE", [50, 200, 250, 212], bold=True),
                    _block("p5_b7", "t-SNE is a popular machine learning algorithm.", [50, 220, 280, 300]),
                ],
            ),
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    roman = [s for s in sem.body.sections if s.heading_element.label == "III."]
    assert len(roman) == 1
    assert any(sub.heading == "Clustering Using t-SNE" and sub.heading_element.label == "B." for sub in roman[0].subsections)


@pytest.mark.skipif(not IEEE_PDF.exists(), reason="IEEE proof PDF not in uploads")
def test_ieee_page1_semantic_elements() -> None:
    raw = extract_text_layout(str(IEEE_PDF))
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert sem.front.title is not None
    assert len(sem.front.title.source_block_ids) >= 3
    assert len(sem.front.authors) >= 1
    assert sem.front.abstract is not None
    assert sem.front.keywords is not None
    assert any(sec.heading_element.label == "I." for sec in sem.body.sections)
    assert "<article-title" in sem.tagged_output
    assert sem.completeness.structured_character_count > 0
    assert sem.completeness.raw_character_count > sem.completeness.excluded_character_count


def test_body_prose_with_who_mention_not_treated_as_reference() -> None:
    raw = _raw(
        [
            _page(
                1,
                [
                    _block(
                        "p1_b1",
                        "Breast cancer (BC) ranks as the predominant form of cancer in adults worldwide, "
                        "with an alarming rate of over 2.3 million new cases each year, as reported by the "
                        "World Health Organization (WHO) 2022.",
                        [50, 200, 550, 260],
                    ),
                    _block(
                        "p1_b2",
                        "Breast cancer survival rates vary significantly across the globe, with a majority "
                        "of deaths occurring in lowand middle-income countries. Early detection is crucial "
                        "as it leads to a clinical cure rate of over 90%.",
                        [50, 270, 550, 330],
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert len(sem.back.references) == 0
    assert all(block.classification != "REFERENCE_TEXT" for block in structure.blocks)


def test_breast_cancer_references_section_parsed_correctly() -> None:
    who_ref = (
        "[1] World Health Organization. Breast Cancer: Prevention and Control. "
        "Accessed: Mar. 16, 2024. [Online]. Available: "
        "https://www.who.int/news-room/fact-sheets/detail/breast-cancer"
    )
    journal_ref = (
        "[2] H. Sung, J. Ferlay, R. L. Siegel, M. Laversanne, I. Soerjomataram, A. Jemal, and F. Bray, "
        "\u201cGlobal cancer statistics 2020: GLOBOCAN estimates of incidence and mortality worldwide "
        "for 36 cancers in 185 countries,\u201d CA: Cancer J. Clinicians, vol. 71, no. 3, pp. 209\u2013249, "
        "May 2021."
    )
    raw = _raw(
        [
            _page(
                8,
                [
                    _block("p8_b1", "REFERENCES", [50, 100, 150, 115], bold=True),
                    _block("p8_b2", who_ref, [50, 130, 550, 170]),
                    _block("p8_b3", journal_ref, [50, 180, 550, 240]),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert len(sem.back.references) == 2
    assert sem.back.references[0].label == "[1]"
    assert "World Health Organization" in sem.back.references[0].text
    assert sem.back.references[1].label == "[2]"
    assert "Global cancer statistics 2020" in sem.back.references[1].text


def test_reference_block_splits_into_multiple_entries() -> None:
    raw = _raw(
        [
            _page(
                8,
                [
                    _block("p8_b1", "REFERENCES", [50, 100, 150, 115], bold=True),
                    _block(
                        "p8_b2",
                        "[1] A. Author, First paper, IEEE, 2020. "
                        "[2] B. Author, Second paper, IEEE, 2021. "
                        "[3] C. Author, Third paper, IEEE, 2022.",
                        [50, 130, 550, 200],
                    ),
                ],
            )
        ]
    )
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    assert len(sem.back.references) == 3
    assert sem.back.references[0].label == "[1]"
    assert "Second paper" in sem.back.references[1].text


def test_table_reconstructed_from_positioned_blocks_multiline_headers() -> None:
    """Borderless tables: rebuild grid from block geometry when find_tables() is empty."""
    caption = _block(
        "p4_b12",
        "TABLE I\nMEASUREMENT SUMMARY",
        [50, 200, 320, 230],
        size=9,
        bold=True,
    )
    grid_blocks = [
        _block("p4_b13", "Sample", [80, 250, 130, 265], size=8),
        _block("p4_b14", "Alpha", [160, 250, 195, 265], size=8),
        _block("p4_b15", "(units)", [160, 268, 205, 283], size=8),
        _block("p4_b16", "Beta", [230, 250, 265, 265], size=8),
        _block("p4_b17", "(units)", [230, 268, 275, 283], size=8),
        _block("p4_b18", "Gamma", [300, 250, 335, 265], size=8),
        _block("p4_b19", "(units)", [300, 268, 345, 283], size=8),
        _block("p4_b20", "R1", [80, 300, 110, 315], size=8),
        _block("p4_b21", "0.638", [160, 300, 200, 315], size=8),
        _block("p4_b22", "0.90", [230, 300, 265, 315], size=8),
        _block("p4_b23", "0.0027", [300, 300, 345, 315], size=8),
        _block("p4_b24", "R2", [80, 320, 110, 335], size=8),
        _block("p4_b25", "0.583", [160, 320, 200, 335], size=8),
        _block("p4_b26", "0.90", [230, 320, 265, 335], size=8),
        _block("p4_b27", "0.0011", [300, 320, 345, 335], size=8),
        _block("p4_b28", "R3", [80, 340, 110, 355], size=8),
        _block("p4_b29", "0.541", [160, 340, 200, 355], size=8),
        _block("p4_b30", "1.10", [230, 340, 265, 355], size=8),
        _block("p4_b31", "0.0010", [300, 340, 345, 355], size=8),
        _block("p4_b32", "R4", [80, 360, 110, 375], size=8),
        _block("p4_b33", "0.714", [160, 360, 200, 375], size=8),
        _block("p4_b34", "1.00", [230, 360, 265, 375], size=8),
        _block("p4_b35", "0.0004", [300, 360, 345, 375], size=8),
        _block("p4_b36", "R5", [80, 380, 110, 395], size=8),
        _block("p4_b37", "0.642", [160, 380, 200, 395], size=8),
        _block("p4_b38", "1.20", [230, 380, 265, 395], size=8),
        _block("p4_b39", "0.0026", [300, 380, 345, 395], size=8),
    ]
    raw = _raw([_page(4, [caption] + grid_blocks)])
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None

    tables = [
        item
        for section in sem.body.sections
        for item in section.content
        if item.type == "table"
    ] + [item for item in sem.body.loose_paragraphs if item.type == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert table.rows is not None
    assert len(table.rows) == 6  # header + 5 data rows
    assert len(table.rows[0]) == 4
    assert table.rows[0][0] == "Sample"
    assert table.rows[0][1] == "Alpha (units)"
    assert table.rows[0][2] == "Beta (units)"
    assert table.rows[0][3] == "Gamma (units)"
    assert table.rows[1] == ["R1", "0.638", "0.90", "0.0027"]
    assert table.rows[5] == ["R5", "0.642", "1.20", "0.0026"]
    assert "MEASUREMENT SUMMARY" in table.text
    assert "<table>" in sem.tagged_output
    assert "<th>Sample</th>" in sem.tagged_output
    assert "<td>0.638</td>" in sem.tagged_output
    assert all(block_id in table.source_block_ids for block_id in ("p4_b13", "p4_b21", "p4_b39"))
    assert "p4_b13" not in sem.completeness.unmapped_block_ids


def test_table_caption_attaches_extracted_rows() -> None:
    page = _page(
        3,
        [_block("p3_b1", "TABLE I\nOPERATIONAL STATISTICS", [50, 200, 300, 230], bold=True)],
    )
    page.tables = [
        ExtractedTable(
            table_id="p3_t0",
            page_number=3,
            rows=[["Parameter", "Value"], ["A", "1"], ["B", "2"]],
        )
    ]
    raw = _raw([page])
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    tables = [
        item
        for section in sem.body.sections
        for item in section.content
        if item.type == "table"
    ] + [item for item in sem.body.loose_paragraphs if item.type == "table"]
    assert len(tables) == 1
    assert tables[0].rows is not None
    assert len(tables[0].rows) == 3
    assert tables[0].rows[0] == ["Parameter", "Value"]
    assert "table-wrap" in sem.tagged_output
    assert "<th>Parameter</th>" in sem.tagged_output


@pytest.mark.skipif(not IEEE_PDF.exists(), reason="IEEE proof PDF not in uploads")
def test_ieee_semantic_classification_quality() -> None:
    raw = extract_text_layout(str(IEEE_PDF))
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None
    tagged = sem.tagged_output

    assert sem.completeness.unknown_element_count == 0
    assert "Clustering Using t-SNE" in tagged
    assert ">B.</label>" in tagged
    assert "Response Recording From e-Tongue" in tagged
    assert "SUBSECTION_HEADING" in tagged or 'data-type="SUBSECTION"' in tagged
    assert ">III.</label>" in tagged
    assert "RESULTS AND DISCUSSIONS" in tagged
    assert "fTAN" in tagged or "disp-formula" in tagged
    assert sem.completeness.unmapped_block_ids == []
