from __future__ import annotations

from app.services.layout.book_copyright_legal import (
    extract_copyright_legal_notices,
    fix_glued_copyright_lines,
    is_book_copyright_boilerplate_line,
    is_book_imprint_block_text,
    split_imprint_glued_text,
)
from app.utils.book_text_typography import apply_book_typography, repair_pdf_stuck_word_boundaries
from app.utils.text_utils import merge_block_texts


def test_fix_glued_available_and_library_of_congress() -> None:
    glued = (
        "British Library Cataloguing in Publication Information Available"
        "Library of Congress Cataloging-in-Publication Data"
    )
    fixed = fix_glued_copyright_lines(glued)
    assert "Available" in fixed and "Library of Congress" in fixed
    assert "AvailableLibrary" not in fixed.replace(" ", "")


def test_merge_block_texts_does_not_join_available_to_library() -> None:
    merged = merge_block_texts(
        [
            "British Library Cataloguing in Publication Information Available",
            "Library of Congress Cataloging-in-Publication Data",
        ]
    )
    assert "Available Library" in merged or "Available\nLibrary" in merged
    assert "AvailableLibrary" not in merged


def test_typography_splits_stuck_camelcase() -> None:
    assert "Available Library" in apply_book_typography("Information AvailableLibrary of Congress")


MOSS_IMPRINT_GLUED = (
    "LEXINGTON BOOKSLanham • Boulder • New York • London Published by Lexington Books "
    "An imprint of The Rowman & Littlefield Publishing Group, Inc.4501 Forbes Boulevard, "
    "Suite 200, Lanham, Maryland 20706www.rowman.com Unit A, Whitacre Mews, "
    "26-34 Stannary Street, London SE11 4AB"
)


def test_repair_lexington_imprint_glue() -> None:
    fixed = repair_pdf_stuck_word_boundaries(MOSS_IMPRINT_GLUED)
    assert "BOOKS Lanham" in fixed
    assert "Inc. 4501" in fixed
    assert "20706 www" in fixed.lower() or "20706 www." in fixed.lower()


def test_split_imprint_into_ordered_lines() -> None:
    lines = split_imprint_glued_text(MOSS_IMPRINT_GLUED)
    assert lines[0].startswith("LEXINGTON BOOKS")
    assert any(line.startswith("Published by") for line in lines)
    assert any("Unit A" in line for line in lines)


def test_imprint_block_detection() -> None:
    assert is_book_imprint_block_text(MOSS_IMPRINT_GLUED)


def test_boilerplate_line_detection() -> None:
    assert is_book_copyright_boilerplate_line(
        "British Library Cataloguing in Publication Information Available"
    )
    assert is_book_copyright_boilerplate_line("Library of Congress Cataloging-in-Publication Data")


def test_extract_legal_notices_from_glued_blob() -> None:
    from app.models.extraction import DocumentInfo, ExtractionResult, ExtractionStats, PageExtraction, TextBlock, TextLine, TextSpan

    block = TextBlock(
        block_id="p2_b0",
        type="text",
        bbox=[50, 100, 400, 200],
        text=(
            "British Library Cataloguing in Publication Information Available"
            "Library of Congress Cataloging-in-Publication Data"
        ),
        lines=[
            TextLine(
                line_id="l0",
                bbox=[50, 100, 400, 120],
                text="British Library Cataloguing in Publication Information AvailableLibrary of Congress Cataloging-in-Publication Data",
                spans=[
                    TextSpan(
                        text="British Library Cataloguing in Publication Information Available",
                        bbox=[50, 100, 400, 110],
                        font="Times",
                        size=10.0,
                        flags=0,
                    ),
                    TextSpan(
                        text="Library of Congress Cataloging-in-Publication Data",
                        bbox=[50, 110, 400, 120],
                        font="Times-Bold",
                        size=10.0,
                        flags=16,
                    ),
                ],
            )
        ],
    )
    page = PageExtraction(
        page_number=2,
        width=432.0,
        height=648.0,
        text_char_count=100,
        requires_ocr=False,
        blocks=[block],
    )
    raw = ExtractionResult(
        document=DocumentInfo(filename="t.pdf", page_count=1, requires_ocr=False),
        pages=[page],
        stats=ExtractionStats(total_chars=100),
    )
    notices = extract_copyright_legal_notices(raw)
    assert len(notices) >= 2
    texts = [str(n["text"]) for n in notices]
    assert any("British Library" in t for t in texts)
    assert any("Library of Congress" in t for t in texts)
