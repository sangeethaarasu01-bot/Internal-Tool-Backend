"""Detect IEEE vendor proof cover pages (author queries) and filter bogus front matter."""

from __future__ import annotations

import re

from app.models.document_structure import ProcessedBlock
from app.models.extraction import ExtractionResult
from app.services.layout.semantic_patterns import normalize_text
from app.utils.template_skeleton import is_boilerplate_text

_AUTHOR_QUERIES_HEADING_RE = re.compile(r"\bauthor\s+queries\b", re.I)
_AQ_LINE_RE = re.compile(r"^AQ:\s*\d+", re.I | re.M)
_AUTHOR_PLEASE_ANSWER_RE = re.compile(r"author\s*:\s*please\s+answer|please\s+answer\s+the\s+following", re.I)
_GATEWAY_NOTICE_RE = re.compile(
    r"author\s+gateway|annotate\s+the\s+pdf|cannot\s+accept\s+new\s+source",
    re.I,
)
_PROOF_COVER_FRAGMENT_RE = re.compile(
    r"\bAQ:\s*\d+|queries\s+regarding|spelling\s+of\s+author|typesetter|proof\s+only|"
    r"not\s+for\s+distribution|vendor\s+query",
    re.I,
)
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\u00C0-\u024F'\-]+")


def is_author_queries_page_text(text: str) -> bool:
    """True when a page is the IEEE/DCL author-queries cover, not article content."""
    normalized = normalize_text(text or "")
    if not normalized.strip():
        return False
    if _AUTHOR_QUERIES_HEADING_RE.search(normalized):
        return True
    aq_count = len(_AQ_LINE_RE.findall(normalized))
    if aq_count >= 2:
        return True
    if aq_count >= 1 and (
        _AUTHOR_PLEASE_ANSWER_RE.search(normalized)
        or _GATEWAY_NOTICE_RE.search(normalized)
        or _AUTHOR_QUERIES_HEADING_RE.search(normalized)
    ):
        return True
    if _GATEWAY_NOTICE_RE.search(normalized) and _AUTHOR_PLEASE_ANSWER_RE.search(normalized):
        return True
    return False


def is_author_queries_heading(text: str) -> bool:
    return bool(_AUTHOR_QUERIES_HEADING_RE.search(normalize_text(text or "")))


def is_proof_cover_fragment(text: str) -> bool:
    """True for short strings that belong to author-query notices, not author bylines."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if is_boilerplate_text(normalized):
        return True
    if _AQ_LINE_RE.match(normalized):
        return True
    if _PROOF_COVER_FRAGMENT_RE.search(normalized):
        return True
    if _AUTHOR_QUERIES_HEADING_RE.search(normalized) and len(normalized) < 120:
        return True
    return False


def is_plausible_author_name(name: str) -> bool:
    """Heuristic filter for real person names (rejects AQ notice fragments)."""
    clean = (name or "").strip()
    if len(clean) < 4 or len(clean) > 100:
        return False
    if is_proof_cover_fragment(clean):
        return False
    if is_boilerplate_text(clean):
        return False
    tokens = _NAME_TOKEN_RE.findall(clean)
    if len(tokens) < 2:
        return False
    capitalized = sum(1 for token in tokens if token[0].isupper() or token.isupper())
    if capitalized < 2:
        return False
    lowered = clean.lower()
    if "corresponding author" in lowered and "@" not in clean and len(tokens) > 6:
        return False
    return True


def detect_author_query_cover_pages(
    processed: list[ProcessedBlock],
    *,
    max_page: int = 3,
) -> set[int]:
    by_page: dict[int, list[str]] = {}
    for block in processed:
        if block.text:
            by_page.setdefault(block.page_number, []).append(block.text)
    cover: set[int] = set()
    for page_number in range(1, max_page + 1):
        chunks = by_page.get(page_number) or []
        if not chunks:
            continue
        joined = "\n".join(chunks)
        if is_author_queries_page_text(joined):
            cover.add(page_number)
    return cover


def article_lead_text_from_phase1(
    phase1: dict | None,
    *,
    max_pages: int = 5,
) -> str:
    """Concatenate early PDF pages, skipping IEEE author-query cover pages."""
    if not phase1:
        return ""
    pages = phase1.get("pages") or []
    chunks: list[str] = []
    for page in pages[:max_pages]:
        if not isinstance(page, dict):
            continue
        text = str(page.get("raw_page_text") or page.get("normalized_text") or "")
        if not text.strip():
            continue
        if is_author_queries_page_text(text):
            continue
        chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    return ""


def is_plausible_journal_title_line(line: str) -> bool:
    """Reject proof-instruction lines misread as journal titles."""
    candidate = (line or "").strip()
    if len(candidate) < 8:
        return False
    if is_author_queries_heading(candidate) or is_proof_cover_fragment(candidate):
        return False
    if is_author_queries_page_text(candidate):
        return False
    lowered = candidate.lower()
    if lowered in {"abstract", "index terms", "keywords"}:
        return False
    return True


def apply_author_query_cover_exclusions(
    raw: ExtractionResult,
    processed: list[ProcessedBlock],
) -> list[ProcessedBlock]:
    """Mark author-query cover pages so they never become title/authors/body."""
    cover_pages = detect_author_query_cover_pages(processed)
    if not cover_pages and raw.pages:
        first = raw.pages[0]
        page_text = "\n".join((block.text or "") for block in first.blocks)
        if is_author_queries_page_text(page_text):
            cover_pages.add(first.page_number)
    if not cover_pages:
        return processed

    updated: list[ProcessedBlock] = []
    for block in processed:
        if block.page_number in cover_pages and not block.exclude_from_content:
            updated.append(
                block.model_copy(
                    update={
                        "exclude_from_content": True,
                        "exclusion_reason": "author_queries_cover",
                    }
                )
            )
        else:
            updated.append(block)
    return updated
