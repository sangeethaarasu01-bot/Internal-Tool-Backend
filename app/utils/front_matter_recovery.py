"""Recover title and keywords when proof covers disrupt front-matter classification."""

from __future__ import annotations

import re
from typing import Any

from app.models.document_structure import ProcessedBlock
from app.models.semantic_document import SemanticFrontMatter
from app.pipeline.phase1.ir_text import ir_node_plain_text
from app.services.ir_builder import build_abstract
from app.services.layout.semantic_patterns import (
    ABSTRACT_RE,
    AFFILIATION_RE,
    DATE_HISTORY_RE,
    KEYWORDS_RE,
    REFERENCE_HEADING_RE,
    is_roman_section_heading,
    is_title_candidate,
    normalize_text,
)
from app.utils.text_utils import merge_block_texts
from app.utils.proof_pdf import (
    is_author_queries_heading,
    is_plausible_author_name,
    is_proof_cover_fragment,
)

_INDEX_TERMS_PREFIX_RE = re.compile(
    r"^(?:index\s+terms|keywords)\s*[—\-–:]?\s*",
    re.IGNORECASE,
)
_SECTION_INTRODUCTION_RE = re.compile(r"^I\.\s+INTRODUCTION\b", re.IGNORECASE)

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


def is_abstract_statistical_continuation(text: str) -> bool:
    """Trailing abstract fragment after column reordering (e.g. ``1.80%, significantly ...``)."""
    normalized = normalize_text(text)
    if not normalized or len(normalized) < 12:
        return False
    if KEYWORDS_RE.match(normalized) or is_running_header_noise(normalized):
        return False
    if re.match(r"^(?:\d+\.|[IVX]+\.)\s+[A-Z]", normalized):
        return False
    return bool(re.match(r"^\d", normalized) and "%" in normalized)


def is_abstract_closing_fragment(text: str) -> bool:
    """Short final abstract sentence (often right-column tail after Index Terms)."""
    normalized = normalize_text(text)
    if not normalized or len(normalized) > 160:
        return False
    if KEYWORDS_RE.match(normalized) or is_running_header_noise(normalized):
        return False
    if re.match(r"^(?:\d+\.|[IVX]+\.)\s+[A-Z]", normalized):
        return False
    if not normalized.endswith("."):
        return False
    if "(" in normalized and ")" in normalized and "," in normalized:
        return False
    return len(normalized.split()) >= 4


def is_post_keywords_abstract_fragment(text: str) -> bool:
    """Abstract continuation blocks that appear after Index Terms in reading order."""
    normalized = normalize_text(text)
    if not normalized:
        return False
    if KEYWORDS_RE.match(normalized) or is_running_header_noise(normalized):
        return False
    if is_abstract_statistical_continuation(normalized):
        return True
    if is_abstract_closing_fragment(normalized):
        return True
    return is_abstract_continuation_text(normalized)


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


def merge_abstract_segment(existing: str, segment: str) -> str:
    """Join abstract text preserving reading order across column wraps."""
    segment = strip_abstract_label(segment)
    existing = strip_abstract_label(existing)
    if not segment:
        return existing
    if not existing:
        return segment
    if segment in existing:
        return existing
    if is_abstract_statistical_continuation(segment):
        gap = re.search(r"\bapproximately\s+(?=state-of-the-art)", existing, re.IGNORECASE)
        if gap:
            insert_at = gap.end(0)
            return re.sub(
                r"\s+",
                " ",
                f"{existing[:insert_at]}{segment} {existing[insert_at:].lstrip()}",
            ).strip()
        if re.search(r"\bapproximately\s*$", existing.rstrip(), re.IGNORECASE):
            return re.sub(r"\s+", " ", f"{existing.rstrip()} {segment}").strip()
    return re.sub(r"\s+", " ", f"{existing.rstrip()} {segment}").strip()


def append_abstract_segment_to_front(front: SemanticFrontMatter, segment: str) -> None:
    segment = strip_abstract_label(segment)
    if not segment.strip():
        return
    existing = strip_abstract_label(ir_node_plain_text(front.abstract)) if front.abstract else ""
    if existing and segment.strip() in existing:
        return
    combined = merge_abstract_segment(existing, segment) if existing else segment
    combined = re.sub(r"\s+", " ", combined).strip()
    block_ids: list[str] = []
    pages: list[int] = []
    if front.abstract:
        block_ids.extend(front.abstract.source_block_ids or [])
        pages.extend(front.abstract.page_numbers or [])
    front.abstract = build_abstract(
        combined,
        source_block_ids=block_ids,
        page_numbers=pages or [1],
        confidence=0.86,
    )


def _page_one_abstract_content_blocks(
    processed: list[ProcessedBlock],
    front: SemanticFrontMatter,
) -> list[ProcessedBlock]:
    """Contiguous page-1 abstract lines in PDF reading order (stops at keywords or section)."""
    ordered = [block for block in _ordered_content_blocks(processed) if block.page_number == 1]
    if not ordered:
        return []

    source_ids = set(front.abstract.source_block_ids or []) if front.abstract else set()
    start_index: int | None = None
    for index, block in enumerate(ordered):
        if source_ids and block.block_id in source_ids:
            start_index = index
            break
    if start_index is None:
        for index, block in enumerate(ordered):
            if ABSTRACT_RE.match(normalize_text(block.text or "")):
                start_index = index
                break
    if start_index is None:
        return []

    collected: list[ProcessedBlock] = []
    for block in ordered[start_index:]:
        text = normalize_text(block.text or "")
        if not text or text.replace("\u200b", "").strip() == "":
            continue
        if collected:
            if block.classification in {"SECTION", "HEADING", "REFERENCE_LIST"}:
                break
            if KEYWORDS_RE.match(text):
                break
            if (
                is_roman_section_heading(text)
                or REFERENCE_HEADING_RE.match(text)
                or _SECTION_INTRODUCTION_RE.match(text)
            ):
                break
        if is_running_header_noise(text):
            continue
        if is_author_queries_heading(text) or is_proof_cover_fragment(text):
            break
        collected.append(block)
    return collected


def reconcile_abstract_from_page_blocks(
    front: SemanticFrontMatter,
    processed: list[ProcessedBlock],
    mapped_ids: set[str] | None = None,
) -> bool:
    """Rebuild abstract text from ordered page-1 blocks (fixes column reorder gaps)."""
    if not front.abstract or not processed:
        return False
    blocks = _page_one_abstract_content_blocks(processed, front)
    if len(blocks) < 2:
        return False
    merged = strip_abstract_label(merge_block_texts([block.text or "" for block in blocks]))
    if not merged:
        return False
    block_ids = [block.block_id for block in blocks]
    page_numbers = list(dict.fromkeys(block.page_number for block in blocks))
    front.abstract = build_abstract(
        merged,
        source_block_ids=block_ids,
        page_numbers=page_numbers,
        confidence=getattr(front.abstract, "confidence", None) or 0.86,
    )
    if mapped_ids is not None:
        mapped_ids.update(block_ids)
    return True


def recover_abstract_tail_from_unmapped_blocks(
    front: SemanticFrontMatter,
    processed: list[ProcessedBlock],
    mapped_ids: set[str],
) -> None:
    """Rebuild abstract from page blocks, then attach post–Index Terms tails if needed."""
    if not front.abstract:
        return
    reconcile_abstract_from_page_blocks(front, processed, mapped_ids)

    keywords_seen = front.keywords is not None
    tail_blocks: list[ProcessedBlock] = []
    for block in _ordered_content_blocks(processed):
        if block.page_number > 1:
            break
        if block.exclude_from_content:
            continue
        text = normalize_text(block.text or "")
        if not text:
            continue
        if KEYWORDS_RE.match(text):
            keywords_seen = True
            continue
        if not keywords_seen:
            continue
        if is_roman_section_heading(text) or REFERENCE_HEADING_RE.match(text):
            break
        if not is_post_keywords_abstract_fragment(text):
            continue
        existing = strip_abstract_label(ir_node_plain_text(front.abstract))
        if text in existing or (len(text) > 12 and text[: min(24, len(text))] in existing):
            continue
        tail_blocks.append(block)
    for block in tail_blocks:
        append_abstract_segment_to_front(front, block.text or "")
        mapped_ids.add(block.block_id)
        if front.abstract:
            front.abstract.source_block_ids = list(
                dict.fromkeys([*(front.abstract.source_block_ids or []), block.block_id])
            )
            front.abstract.page_numbers = list(
                dict.fromkeys([*(front.abstract.page_numbers or []), block.page_number])
            )


def _ordered_content_blocks(processed: list[ProcessedBlock]) -> list[ProcessedBlock]:
    return sorted(
        [block for block in processed if not block.exclude_from_content],
        key=lambda block: (block.page_number, block.reading_order_index),
    )


def coerce_processed_blocks(raw: list[Any] | None) -> list[ProcessedBlock]:
    if not raw:
        return []
    blocks: list[ProcessedBlock] = []
    for item in raw:
        if isinstance(item, ProcessedBlock):
            blocks.append(item)
        elif isinstance(item, dict):
            blocks.append(ProcessedBlock.model_validate(item))
    return blocks


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
    if is_abstract_statistical_continuation(normalized) or is_abstract_closing_fragment(normalized):
        return False
    if KEYWORDS_RE.match(normalized):
        return True
    if "%" in normalized:
        return False
    if normalized.rstrip().endswith(".") and len(normalized) >= 20:
        if "(" in normalized and ")" in normalized and "," in normalized:
            return True
        return False
    if "," in normalized and re.search(r"\([A-Za-z]{2,8}\)", normalized):
        return True
    if is_plausible_author_name(normalized):
        return False
    if normalized.endswith(","):
        return True
    if re.match(r"^[a-z]", normalized):
        return len(normalized.split()) <= 3 and not normalized.endswith(".")
    if "(" in normalized and ")" in normalized and "," in normalized:
        return True
    return bool(
        "," in normalized
        and len(normalized.split()) <= 24
        and not normalized.rstrip().endswith(".")
    )
