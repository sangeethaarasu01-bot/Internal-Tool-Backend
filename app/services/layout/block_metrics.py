"""Font and visual metrics derived from block lines/spans."""

from __future__ import annotations

from collections import Counter

from app.models.extraction import TextBlock


def block_font_metrics(block: TextBlock) -> tuple[str | None, float | None, bool]:
    fonts: Counter[str] = Counter()
    sizes: Counter[float] = Counter()
    bold_hits = 0
    span_count = 0

    for line in block.lines:
        for span in line.spans:
            if span.font:
                fonts[span.font] += len(span.text)
            if span.size:
                sizes[round(span.size, 1)] += len(span.text)
            span_count += 1
            if span.flags is not None and span.flags & 2:
                bold_hits += 1

    dominant_font = fonts.most_common(1)[0][0] if fonts else None
    dominant_size = sizes.most_common(1)[0][0] if sizes else None
    is_bold = span_count > 0 and bold_hits >= max(1, span_count // 2)
    return dominant_font, dominant_size, is_bold


def median_body_font_size(blocks: list[tuple[TextBlock, str]]) -> float:
    """Median font size from content-like blocks (classification label as str)."""
    sizes: list[float] = []
    for block, _classification in blocks:
        _, size, _ = block_font_metrics(block)
        if size and len((block.text or "").strip()) > 40:
            sizes.append(size)
    if not sizes:
        return 10.0
    sizes.sort()
    mid = len(sizes) // 2
    return sizes[mid]
