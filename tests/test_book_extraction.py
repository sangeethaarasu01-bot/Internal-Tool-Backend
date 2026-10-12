from __future__ import annotations

from pathlib import Path

import pytest

from app.models.extraction import DocumentInfo, ExtractionResult, ExtractionStats, PageExtraction, TextBlock, TextLine, TextSpan
from app.pipeline.phase1.build_document import build_extracted_document
from app.services.layout.document_pipeline import process_document_structure
from app.services.layout.book_metadata import (
    detect_book_document,
    extract_book_title,
    extract_title_from_loc_cip,
    extract_title_from_title_page,
    is_plausible_book_author_name,
    is_rejected_book_title_candidate,
    is_valid_book_title,
    normalize_book_author_name,
)
from app.services.layout.book_patterns import looks_like_book_chapter_reference_line
from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
IEEE_PDF = ROOT / "uploads" / "20260907_132003_jsen-banerjeeroy-3639180-proof1.pdf"
DEBUG = ROOT / "data" / "pipeline_debug"


def _block(block_id: str, text: str, bbox: list[float], size: float = 11.0, bold: bool = False) -> TextBlock:
    flags = 16 if bold else 0
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
                spans=[TextSpan(text=text, bbox=bbox, font="Helvetica", size=size, flags=flags)],
            )
        ],
    )


def _page(page_number: int, blocks: list[TextBlock]) -> PageExtraction:
    text = "".join(b.text for b in blocks)
    return PageExtraction(
        page_number=page_number,
        width=612.0,
        height=792.0,
        text_char_count=len(text),
        requires_ocr=False,
        blocks=blocks,
    )


def _marshall_like_book() -> ExtractionResult:
    """Synthetic front matter + two chapters with per-chapter references."""
    pages = [
        _page(
            1,
            [
                _block("p1_b0", "Overcoming Student Apathy", [50, 200, 500, 240], size=22.0, bold=True),
                _block("p1_b1", "Succeeding with All Learners 2nd edition", [50, 250, 500, 280], size=18.0),
                _block("p1_b2", "JEFF C. MARSHALL", [50, 320, 400, 340], size=12.0),
            ],
        ),
        _page(
            2,
            [
                _block(
                    "p2_b0",
                    "ISBN 978-1-4758-0660-1\n"
                    "Library of Congress Cataloging-in-Publication Data\n"
                    "Marshall, Jeff C., 1965- Overcoming student apathy : succeeding with all learners / Jeff C. Marshall.\n"
                    "Includes bibliographical references.\n"
                    "© 2014 Rowman & Littlefield. All rights reserved.\n"
                    "Published by Rowman & Littlefield",
                    [50, 80, 550, 400],
                ),
            ],
        ),
        _page(
            19,
            [
                _block("p19_b0", "ONE  The Rebel  September 23", [50, 100, 500, 130], size=16.0, bold=True),
                _block(
                    "p19_b1",
                    "Chapter body about engagement and classroom culture for reluctant learners.",
                    [50, 150, 550, 700],
                ),
            ],
        ),
        _page(
            31,
            [
                _block("p31_b0", "REFERENCES", [50, 100, 200, 120], bold=True),
                _block(
                    "p31_b1",
                    "Gladwell, M. Outliers: The Story of Success. Little, Brown and Company, 2008.",
                    [50, 130, 550, 160],
                ),
                _block(
                    "p31_b2",
                    "Greene, R. W. Lost at School. Scribner, 2014.",
                    [50, 170, 550, 200],
                ),
            ],
        ),
        _page(
            33,
            [
                _block("p33_b0", "TWO  The Socialite  October 11", [50, 100, 500, 130], size=16.0, bold=True),
                _block("p33_b1", "Second chapter narrative about social dynamics in the classroom.", [50, 150, 550, 400]),
            ],
        ),
        _page(
            44,
            [
                _block("p44_b0", "REFERENCES", [50, 100, 200, 120], bold=True),
                _block(
                    "p44_b1",
                    "Kagan, S. Cooperative Learning. Kagan Publishing, 1994.",
                    [50, 130, 550, 160],
                ),
            ],
        ),
        _page(
            45,
            [
                _block(
                    "p45_b0",
                    "Intermission 1: Keystone Habits",
                    [50, 100, 500, 130],
                    size=15.0,
                    bold=True,
                ),
            ],
        ),
    ]
    return ExtractionResult(
        document=DocumentInfo(filename="9798216211488_web.pdf", page_count=len(pages), requires_ocr=False),
        pages=pages,
        stats=ExtractionStats(
            total_blocks=sum(len(p.blocks) for p in pages),
            total_lines=sum(len(b.lines) for p in pages for b in p.blocks),
            total_chars=sum(p.text_char_count for p in pages),
        ),
    )


def _moss_political_poetry_title_pages() -> ExtractionResult:
    pages = [
        _page(
            1,
            [
                _block(
                    "p1_b0",
                    "Political Poetry in the Wake of the Second Spanish Republic",
                    [50, 200, 520, 240],
                    size=22.0,
                    bold=True,
                ),
                _block(
                    "p1_b1",
                    "Rafael Alberti, Pablo Neruda, and Nicolás Guillén",
                    [50, 260, 520, 290],
                    size=14.0,
                ),
                _block("p1_b2", "Grant D. Moss", [50, 320, 400, 345], size=12.0),
            ],
        ),
        _page(
            2,
            [
                _block(
                    "p2_b0",
                    "Published by Lexington Books\n"
                    "An imprint of The Rowman & Littlefield Publishing Group, Inc.\n"
                    "4501 Forbes Boulevard, Suite 200, Lanham, Maryland 20706\n"
                    "www.rowman.com\n\n"
                    "Copyright © 2018 by Lexington Books\n"
                    "ISBN 978-1-4985-4770-3 (cloth : alk. paper)\n"
                    "ISBN 978-1-4985-4771-0 (electronic)",
                    [50, 80, 550, 400],
                ),
            ],
        ),
    ]
    return ExtractionResult(
        document=DocumentInfo(filename="political_poetry.pdf", page_count=len(pages), requires_ocr=False),
        pages=pages,
        stats=ExtractionStats(
            total_blocks=sum(len(p.blocks) for p in pages),
            total_lines=sum(len(b.lines) for p in pages for b in p.blocks),
            total_chars=sum(p.text_char_count for p in pages),
        ),
    )


def test_title_page_on_page_four_after_copyright() -> None:
    pages = [
        _page(1, [_block("p1", "Copyright © 2018", [50, 80, 400, 100])]),
        _page(2, [_block("p2", "ISBN 978-1-4985-4770-3", [50, 80, 400, 100])]),
        _page(3, [_block("p3", "Published by Lexington Books", [50, 80, 400, 100])]),
        _page(
            4,
            [
                _block(
                    "p4_t",
                    "Political Poetry in the Wake\nof the Second Spanish Republic",
                    [50, 200, 520, 260],
                    size=22.0,
                ),
                _block(
                    "p4_s",
                    "Rafael Alberti, Pablo Neruda, and Nicolás Guillén",
                    [50, 270, 520, 300],
                    size=14.0,
                ),
                _block("p4_a", "Grant D. Moss", [50, 320, 400, 345], size=12.0),
            ],
        ),
    ]
    raw = ExtractionResult(
        document=DocumentInfo(filename="p4_title.pdf", page_count=4, requires_ocr=False),
        pages=pages,
        stats=ExtractionStats(total_blocks=5, total_lines=5, total_chars=200),
    )
    from app.services.layout.book_metadata import extract_title_page_triplet

    title, subtitle, author = extract_title_page_triplet(raw)
    assert "Second Spanish Republic" in (title or "")
    assert "Wake" in (title or "")
    assert "Neruda" in (subtitle or "")
    assert author == "Grant D. Moss"


def test_author_name_from_about_the_author_blurb() -> None:
    from app.services.layout.book_author_bio import extract_author_name_from_about_blurb

    tail_page = _page(
        200,
        [
            _block("about", "About the Author", [50, 100, 200, 120], bold=True),
            _block(
                "bio",
                "Grant D. Moss is an Associate Professor of Spanish at the University of Utah. "
                "He has published widely on modern Iberian poetry.",
                [50, 140, 550, 220],
            ),
        ],
    )
    raw = ExtractionResult(
        document=DocumentInfo(filename="bio.pdf", page_count=200, requires_ocr=False),
        pages=[tail_page],
        stats=ExtractionStats(total_blocks=2, total_lines=2, total_chars=120),
    )
    assert extract_author_name_from_about_blurb(raw) == "Grant D. Moss"


def test_lexington_political_poetry_title_page_metadata() -> None:
    raw = _moss_political_poetry_title_pages()
    ctx = detect_book_document(raw)
    assert ctx.is_book
    assert ctx.title == "Political Poetry in the Wake of the Second Spanish Republic"
    assert "Neruda" in (ctx.subtitle or "")
    assert "Alberti" in (ctx.subtitle or "")
    assert ctx.author == "Grant D. Moss"
    assert ctx.publisher_imprint == "Lexington Books"
    assert ctx.publisher and "Rowman" in ctx.publisher and "Littlefield" in ctx.publisher
    assert any(addr.street and "Forbes" in addr.street for addr in ctx.publisher_addresses)
    assert ctx.copyright_holder == "Lexington Books"
    assert ctx.year == 2018
    assert len(ctx.isbns) == 2
    assert ctx.isbn == "978-1-4985-4770-3"
    assert ("978-1-4985-4770-3", "hardback") in ctx.isbn_roles


def test_book_metadata_detection() -> None:
    raw = _marshall_like_book()
    ctx = detect_book_document(raw)
    assert ctx.is_book
    assert ctx.publication_document_type == "book"
    assert ctx.title == "Overcoming Student Apathy: Succeeding with All Learners"
    assert ctx.author == "Jeff C. Marshall"
    assert ctx.publisher == "Rowman & Littlefield"
    assert ctx.year == 2014
    assert ctx.isbn and "978-1-4758-0660-1".replace("-", "") in ctx.isbn.replace("-", "")


def test_reject_published_as_title() -> None:
    assert is_rejected_book_title_candidate("Published")
    assert is_rejected_book_title_candidate("Published by Rowman & Littlefield")


def test_normalize_author_strips_all_rights() -> None:
    assert normalize_book_author_name("Jeff C. Marshall All") == "Jeff C. Marshall"
    assert normalize_book_author_name("Jeff C. Marshall") == "Jeff C. Marshall"


def test_loc_cip_catalog_line_title_and_author() -> None:
    from app.services.layout.book_metadata import _extract_author_from_text

    catalog = (
        "Marshall, Jeff C., 1965- Overcoming student apathy : succeeding with all learners "
        "/ Jeff C. Marshall."
    )
    assert (
        extract_title_from_loc_cip(catalog)
        == "Overcoming Student Apathy: Succeeding with All Learners"
    )
    author = _extract_author_from_text(catalog, catalog)
    assert author == "Jeff C. Marshall"


def test_normalized_title_strips_slash_author_suffix() -> None:
    from app.services.layout.book_metadata import normalize_book_title, _strip_title_author_slash_suffix

    raw = (
        "Overcoming student apathy : succeeding with all learners / Jeff C. Marshall"
    )
    assert (
        _strip_title_author_slash_suffix(normalize_book_title(raw))
        == "Overcoming Student Apathy: Succeeding with All Learners"
    )


def test_loc_title_drops_author_suffix_after_slash() -> None:
    catalog = (
        "Marshall, Jeff C., 1965- Overcoming student apathy : succeeding with all learners "
        "/ Jeff C. Marshall. Includes bibliographical references."
    )
    title = extract_title_from_loc_cip(catalog)
    assert title == "Overcoming Student Apathy: Succeeding with All Learners"
    assert "/" not in (title or "")
    assert "Marshall" not in (title or "")


def test_loc_title_wins_over_copyright_boilerplate() -> None:
    blob = (
        "Marshall, Jeff C., 1965- Overcoming student apathy : succeeding with all learners "
        "/ Jeff C. Marshall.\n"
        "16 Carlisle Street, London W1d 3bt, United Kingdom: Electronic or Mechanical Means, "
        "Including Information Storage and Retrieval Systems,"
    )
    assert (
        extract_title_from_loc_cip(blob)
        == "Overcoming Student Apathy: Succeeding with All Learners"
    )
    assert not is_valid_book_title(
        "16 Carlisle Street, London W1d 3bt, United Kingdom: Electronic or Mechanical Means, "
        "Including Information Storage and Retrieval Systems,"
    )


def test_title_page_fallback_strips_edition() -> None:
    raw = _marshall_like_book()
    # Remove CIP from page 2 so title page strategy is exercised.
    raw.pages[1].blocks[0].text = "ISBN 978-1-4758-0660-1\n© 2014 Rowman & Littlefield."
    title = extract_title_from_title_page(raw)
    assert title == "Overcoming Student Apathy"


def test_extract_book_title_priority_chain() -> None:
    raw = _marshall_like_book()
    front = "\n".join(block.text for page in raw.pages[:2] for block in page.blocks)
    assert (
        extract_book_title(front, raw)
        == "Overcoming Student Apathy: Succeeding with All Learners"
    )


def test_copyright_by_preserves_middle_initial() -> None:
    from app.services.layout.book_metadata import _extract_author_from_text

    text = "© 2014 by Jeff C. Marshall. All rights reserved."
    author = _extract_author_from_text(text, text)
    assert author == "Jeff C. Marshall"


def _normalize_title_for_compare(title: str) -> str:
    return " ".join(title.split()).strip().lower()


MARSHALL_PDF = ROOT / "uploads" / "9798216211488_web.pdf"


@pytest.mark.skipif(not MARSHALL_PDF.is_file(), reason="Marshall book PDF not in uploads/")
def test_marshall_book_pdf_metadata() -> None:
    raw = extract_text_layout(str(MARSHALL_PDF), original_filename=MARSHALL_PDF.name)
    doc = build_extracted_document(raw, structure=process_document_structure(raw, include_tagged_output=False))
    expected_title = "Overcoming Student Apathy: Succeeding with All Learners"
    assert doc.document_type == "book"
    assert _normalize_title_for_compare(doc.title or "") == _normalize_title_for_compare(expected_title)
    assert doc.authors == ["Jeff C. Marshall"]
    assert len(doc.sections) >= 12
    assert 20 <= len(doc.references) <= 60


def test_book_bibliography_line_filter() -> None:
    assert looks_like_book_chapter_reference_line(
        "Gladwell, M. (2008). Outliers: The Story of Success. Little, Brown and Company."
    )
    assert not looks_like_book_chapter_reference_line("(Gladwell 2000)")
    assert not looks_like_book_chapter_reference_line("As Gladwell noted in his work.")


def test_book_structure_and_references() -> None:
    raw = _marshall_like_book()
    structure = process_document_structure(raw, include_tagged_output=False)
    doc = build_extracted_document(raw, structure=structure)

    assert doc.publication_document_type == "book"
    assert doc.document_type == "book"
    assert doc.title == "Overcoming Student Apathy: Succeeding with All Learners"
    assert doc.authors == ["Jeff C. Marshall"]
    assert doc.publisher == "Rowman & Littlefield"
    assert doc.publication_year == 2014

    headings = [s.heading for s in doc.sections]
    assert any("Chapter 1" in h and "Rebel" in h for h in headings)
    assert any("Chapter 2" in h and "Socialite" in h for h in headings)
    assert any("Intermission 1" in h for h in headings)
    assert len(doc.sections) >= 3
    assert len(doc.references) >= 2
    assert any("Gladwell" in ref.text for ref in doc.references)
    assert any("Kagan" in ref.text for ref in doc.references)


def test_plausible_book_author_rejects_copyright_noise() -> None:
    assert not is_plausible_book_author_name("Published by Rowman & Littlefield, Inc.")
    assert is_plausible_book_author_name("Jeff C. Marshall")


@pytest.mark.skipif(not IEEE_PDF.is_file(), reason="IEEE sample PDF not present")
def test_research_paper_still_not_book() -> None:
    raw = extract_text_layout(str(IEEE_PDF), original_filename=IEEE_PDF.name)
    structure = process_document_structure(raw, include_tagged_output=False)
    assert structure.publication_document_type == "research_paper"
    assert len(structure.sections) >= 1


@pytest.mark.parametrize(
    "fixture_dir",
    [
        "tap-mao-3657825-proof.pdf1.pdf",
        "access-kakichi-3657695-proof.pdf1.pdf",
        "jssc-qin-3657757-test",
    ],
)
def test_regression_debug_pdfs_remain_research_papers(fixture_dir: str) -> None:
    manifest = DEBUG / fixture_dir / "manifest.json"
    if not manifest.is_file():
        pytest.skip(f"debug bundle missing: {fixture_dir}")
    pdf_name = None
    import json

    data = json.loads(manifest.read_text(encoding="utf-8"))
    pdf_name = data.get("source_pdf") or data.get("pdf")
    if not pdf_name:
        pytest.skip("no pdf in manifest")
    pdf_path = ROOT / "uploads" / pdf_name
    if not pdf_path.is_file():
        pdf_path = DEBUG / fixture_dir / pdf_name
    if not pdf_path.is_file():
        pytest.skip(f"pdf not found for {fixture_dir}")
    raw = extract_text_layout(str(pdf_path), original_filename=pdf_path.name)
    structure = process_document_structure(raw, include_tagged_output=False)
    assert structure.publication_document_type == "research_paper"
