from __future__ import annotations

from app.services.layout.book_copyright_legal import (
    extract_copyright_legal_notices,
    fix_glued_copyright_lines,
    is_book_copyright_boilerplate_line,
)
from app.utils.book_text_typography import apply_book_typography
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
