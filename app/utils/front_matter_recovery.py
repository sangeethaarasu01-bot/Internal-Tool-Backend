"""Recover title and keywords when proof covers disrupt front-matter classification."""

from __future__ import annotations

import re

from app.models.document_structure import ProcessedBlock
from app.services.layout.semantic_patterns import (
    ABSTRACT_RE,
    AFFILIATION_RE,
    DATE_HISTORY_RE,
    KEYWORDS_RE,
    is_title_candidate,
    normalize_text,
)
from app.utils.proof_pdf import (
    is_author_queries_heading,
    is_plausible_author_name,
    is_proof_cover_fragment,
)

_INDEX_TERMS_PREFIX_RE = re.compile(
    r"^(?:index\s+terms|keywords)\s*[—\-–:]?\s*",
    re.IGNORECASE,
)
_JOURNAL_BANNER_RE = re.compile(
    r"^(?:IEEE\s+(?:Transactions|Access)|VOLUME\s+\d+|Digital Object Identifier|10\.\d{4}/)",
    re.IGNORECASE,
)
_RUNNING_HEADER_PAGE_RE = re.compile(
    r"^IEEE\s+.+\s+\d{1,3}\s*$",
    re.IGNORECASE,
)
_ABSTRACT_LABEL_RE = re.compile(r"^abstract\s*[—\-–:]\s*", re.IGNORECASE)


def strip_abstract_label(text: str) -> str:
    return _ABSTRACT_LABEL_RE.sub("", normalize_text(text)).strip()


def is_running_header_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    if _RUNNING_HEADER_PAGE_RE.match(normalized):
        return True
    return _is_journal_banner(normalized)


def is_abstract_continuation_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized or len(normalized) > 1200:
        return False
    if KEYWORDS_RE.match(normalized) or is_running_header_noise(normalized):
        return False
    if is_author_queries_heading(normalized) or is_proof_cover_fragment(normalized):
        return False
    if re.match(r"^(?:\d+\.|[IVX]+\.)\s+[A-Z]", normalized):
        return False
    if ABSTRACT_RE.match(normalized):
        return True
    if is_plausible_author_name(normalized) and len(normalized.split()) <= 8:
        return False
    return len(normalized) >= 24


def _ordered_content_blocks(processed: list[ProcessedBlock]) -> list[ProcessedBlock]:
    return sorted(
        [block for block in processed if not block.exclude_from_content],
        key=lambda block: (block.page_number, block.reading_order_index),
    )


def _stops_title_scan(text: str) -> bool:
    return bool(
        ABSTRACT_RE.match(text)
        or KEYWORDS_RE.match(text)
        or DATE_HISTORY_RE.match(text)
        or is_author_queries_heading(text)
        or is_proof_cover_fragment(text)
    )


def _is_journal_banner(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized or len(normalized) > 160:
        return False
    if _JOURNAL_BANNER_RE.match(normalized):
        return True
    upper = normalized.upper()
    return "IEEE TRANSACTIONS" in upper and len(normalized.split()) <= 14


def recover_article_title(
    processed: list[ProcessedBlock],
    title_threshold: float,
    *,
    can_merge_title,
) -> tuple[str, list[ProcessedBlock], float] | None:
    """Pick article title from the first real content page (post proof cover)."""
    ordered = _ordered_content_blocks(processed)
    if not ordered:
        return None

    first_page = ordered[0].page_number
    title_blocks: list[ProcessedBlock] = []

    for block in ordered:
        if block.page_number > first_page + 1:
            break
        text = normalize_text(block.text)
        if not text:
            continue
        if _stops_title_scan(text):
            break
        if _is_journal_banner(text):
            continue
        if is_plausible_author_name(text) and len(text.split()) <= 6:
            continue
        if AFFILIATION_RE.search(text) and block.page_number == first_page:
            continue

        if title_blocks:
            if can_merge_title(title_blocks[-1], block, title_threshold):
                title_blocks.append(block)
                continue
            break

        if is_title_candidate(block, title_threshold):
            title_blocks.append(block)
            continue

        if (
            block.page_number == first_page
            and len(text) >= 40
            and (block.dominant_font_size or 0) >= title_threshold - 1.5
            and not is_plausible_author_name(text)
        ):
            title_blocks.append(block)

    if not title_blocks:
        return None

    merged = " ".join(normalize_text(block.text) for block in title_blocks)
    merged = re.sub(r"\s+", " ", merged).strip()
    if len(merged) < 20 or is_author_queries_heading(merged):
        return None
    confidence = 0.82 if len(title_blocks) == 1 else 0.86
    return merged, title_blocks, confidence


def parse_index_terms_keywords(text: str) -> list[str]:
    """Split IEEE index terms without leaving truncated phrase tails."""
    cleaned = _INDEX_TERMS_PREFIX_RE.sub("", normalize_text(text)).strip(" —-–:")
    if not cleaned:
        return []
    parts = [part.strip() for part in re.split(r",\s*", cleaned) if part.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(part.split()) <= 2 and not part[0].isupper():
            merged[-1] = f"{merged[-1]}, {part}"
        elif merged and len(merged[-1].split()) <= 2 and part.lower().startswith(
            ("health", "charge", "learning", "estimation", "vehicle")
        ):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def is_keywords_continuation(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized or len(normalized) > 220:
        return False
    if _stops_title_scan(normalized) or _is_journal_banner(normalized):
        return False
    if AFFILIATION_RE.search(normalized) and "@" in normalized:
        return False
    if KEYWORDS_RE.match(normalized):
        return True
    if "," in normalized and re.search(r"\([A-Za-z]{2,8}\)", normalized):
        return True
    if is_plausible_author_name(normalized):
        return False
    if normalized.endswith(","):
        return True
    if re.match(r"^[a-z]", normalized):
        return True
    if "(" in normalized and ")" in normalized and "," in normalized:
        return True
    return bool("," in normalized and len(normalized.split()) <= 24)
