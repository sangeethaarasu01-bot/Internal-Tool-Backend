"""Detect books and extract title/author/publisher metadata from front matter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.models.extraction import ExtractionResult
from app.pipeline.phase1.text_fidelity import join_ordered_block_text
from app.services.layout.semantic_patterns import normalize_text
from app.services.layout.book_author_bio import (
    extract_about_the_author_blurb,
    extract_author_name_from_about_blurb,
)
from app.services.layout.book_publisher_address import (
    PublisherAddress,
    extract_publisher_addresses,
)
from app.utils.isbn_selection import (
    extract_isbn_entries,
    role_from_isbn_qualifier,
    select_primary_isbn,
)

PublicationDocumentType = Literal["research_paper", "book", "review", "unknown"]

ISBN_RE = re.compile(r"\bISBN(?:-1[03])?:?\s*([\d\-Xx]{10,17})", re.IGNORECASE)
COPYRIGHT_YEAR_RE = re.compile(r"(?:©|Copyright)\s*(?:©\s*)?(\d{4})", re.IGNORECASE)
COPYRIGHT_BY_AUTHOR_RE = re.compile(
    r"(?:©|Copyright)\s*(?:©\s*)?\d{4}\s+by\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)*(?:\s+[A-Z][a-z.'\-]+)+)"
    r"(?:\.(?:\s+All\b)|,|\s+All\b)",
    re.IGNORECASE,
)
COPYRIGHT_BY_HOLDER_RE = re.compile(
    r"(?:©|Copyright)\s*(?:©\s*)?\d{4}\s+by\s+([^\n.]+?)(?:\.\s*(?:All rights)|\s+All rights|\n|$)",
    re.IGNORECASE,
)
IMPRINT_OF_RE = re.compile(
    r"An imprint of\s+(.+?)(?:\s*\n|$)",
    re.IGNORECASE,
)
CATALOG_LINE_RE = re.compile(
    r"^(.+?\s+:\s+.+?)\s*/\s*([^,\n/]+?)\s*,\s*(\d{4})-",
    re.IGNORECASE,
)
# Surname-first LOC/CIP: Marshall, Jeff C., 1965- Title : subtitle / Jeff C. Marshall.
LOC_CIP_RECORD_RE = re.compile(
    r"(?is)"
    r"[A-Za-z'\-]+,\s+[A-Za-z.'\-\s]+?,?\s*\d{4}-\s*"
    r"(.+?\s+:\s+.+?)\s*/\s*"
    r"([A-Z][a-z]+(?:\s+(?:[A-Z]\.|[A-Z][a-z'\-]+)){1,4})"
    r"(?:\.\s*(?=\d|[A-Za-z])|\s*,\s*\d{4}-|\s*\.?\s*$)",
)
CATALOG_INLINE_RE = re.compile(
    r"([A-Za-z][^/\n]{8,120}?\s+:\s+[^/\n]{5,120}?)\s*/\s*([A-Za-z][^,\n/]{2,60}?)\s*,\s*(\d{4})-",
    re.IGNORECASE,
)
TITLE_PAGE_BY_AUTHOR_RE = re.compile(
    r"(?is)(.+?)\s+by\s+([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)*(?:\s+[A-Z][a-z.'\-]+)+)\b",
)
BY_AUTHOR_RE = re.compile(
    r"\bby\s+([A-Z][A-Za-z.'\-]+(?:\s+(?:[A-Z]\.?|[A-Z][a-z.'\-]+)){1,4})",
    re.IGNORECASE,
)
PUBLISHER_MARKERS = (
    "Rowman & Littlefield",
    "Rowman and Littlefield",
    "Palgrave Macmillan",
    "Springer",
    "Wiley",
    "Elsevier",
    "Routledge",
    "Oxford University Press",
    "Cambridge University Press",
)
SPELLED_CHAPTER_MARKER_RE = re.compile(
    r"\b(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)\s+The\s+",
    re.IGNORECASE,
)
REJECT_TITLE_WORDS = frozenset(
    {
        "published",
        "copyright",
        "book",
        "page",
        "chapter",
        "isbn",
        "library",
        "contents",
        "preface",
        "title",
    }
)
COPYRIGHT_TITLE_BOILERPLATE = (
    "street",
    "boulevard",
    "suite",
    "london",
    "united kingdom",
    "electronic or mechanical",
    "storage and retrieval",
    "all rights reserved",
    "no part of this publication",
    "library of congress",
    "cataloging-in-publication",
    "published by",
    "permission",
    "reproduced",
    "transmitted",
)
TITLE_SMALL_WORDS = frozenset(
    {"a", "an", "and", "of", "the", "with", "for", "in", "to", "or"},
)
EDITION_SUFFIX_RE = re.compile(r"\s*\d+(?:st|nd|rd|th)\s+edition\b", re.IGNORECASE)
STREET_ADDRESS_RE = re.compile(
    r"^\d{1,5}\s+[A-Za-z0-9'\.\s]+(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|drive|dr\.?|lane|ln\.?)\b",
    re.IGNORECASE,
)
PERSON_NAME_RE = re.compile(
    r"^([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)*(?:\s+[A-Z][a-z.'\-]+)+)$",
)


@dataclass(frozen=True)
class BookExtractionContext:
    is_book: bool = False
    publication_document_type: PublicationDocumentType = "research_paper"
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    publisher: str | None = None
    publisher_imprint: str | None = None
    publisher_trade_name: str | None = None
    author_blurb: str | None = None
    publisher_addresses: tuple[PublisherAddress, ...] = ()
    year: int | None = None
    isbn: str | None = None
    isbns: tuple[str, ...] = ()
    isbn_roles: tuple[tuple[str, str], ...] = ()
    copyright_holder: str | None = None


def _early_pages_text(raw: ExtractionResult, max_pages: int = 25) -> str:
    parts: list[str] = []
    for page in sorted(raw.pages, key=lambda p: p.page_number):
        if page.page_number > max_pages:
            break
        parts.append(join_ordered_block_text(raw, page_number=page.page_number))
    return "\n".join(parts)


def _front_matter_pages_text(raw: ExtractionResult, max_pages: int = 10) -> str:
    parts: list[str] = []
    for page in sorted(raw.pages, key=lambda p: p.page_number):
        if page.page_number > max_pages:
            break
        parts.append(join_ordered_block_text(raw, page_number=page.page_number))
    return "\n".join(parts)


def _full_text_sample(raw: ExtractionResult, max_chars: int = 120_000) -> str:
    return join_ordered_block_text(raw)[:max_chars]


def is_rejected_book_title_candidate(title: str) -> bool:
    return not is_valid_book_title(title)


def is_valid_book_title(title: str) -> bool:
    cleaned = normalize_text(title).strip()
    if not cleaned or len(cleaned) < 8:
        return False
    if len(cleaned) > 250:
        return False
    lowered = cleaned.lower()
    if lowered in REJECT_TITLE_WORDS:
        return False
    meaningful_words = [w for w in re.findall(r"[A-Za-z0-9']+", cleaned) if len(w) > 1]
    if len(meaningful_words) < 3:
        return False
    if STREET_ADDRESS_RE.search(cleaned):
        return False
    if any(phrase in lowered for phrase in COPYRIGHT_TITLE_BOILERPLATE):
        return False
    reject_prefixes = (
        "published by",
        "copyright",
        "all rights",
        "library of congress",
        "cataloging-in-publication",
    )
    if any(lowered.startswith(prefix) for prefix in reject_prefixes):
        return False
    if "isbn" in lowered or "www." in lowered or "http" in lowered:
        return False
    if len(cleaned.split()) < 3 and ":" not in cleaned:
        return False
    return True


def normalize_book_author_name(raw_name: str) -> str | None:
    cleaned = normalize_text(raw_name).strip().rstrip(".,;")
    if not cleaned:
        return None
    cleaned = re.sub(r"\s+All\s+rights.*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+All$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r",\s*\d{4}-.*$", "", cleaned).strip()
    cleaned = re.sub(r"\s+by\s+.*$", "", cleaned, flags=re.IGNORECASE).strip()

    match = PERSON_NAME_RE.match(cleaned)
    if match:
        return match.group(1).strip()

    tokens = cleaned.split()
    name_tokens: list[str] = []
    stop_words = {"all", "rights", "reserved", "by", "copyright", "published", "the", "and"}
    for token in tokens:
        if token.lower() in stop_words:
            break
        if not re.match(r"^[A-Z][A-Za-z.'\-]*$", token):
            break
        name_tokens.append(token)
        if len(name_tokens) >= 4:
            break
    if len(name_tokens) < 2:
        return None
    candidate = " ".join(name_tokens)
    return candidate if is_plausible_book_author_name(candidate) else None


def is_plausible_book_author_name(name: str) -> bool:
    cleaned = normalize_text(name).strip()
    if not cleaned or len(cleaned) > 80:
        return False
    lowered = cleaned.lower()
    reject_phrases = (
        "published by",
        "all rights reserved",
        "library of congress",
        "isbn",
        "cataloging-in-publication",
        "permission",
        "rowman",
        "littlefield",
        "www.",
        "http",
    )
    if any(phrase in lowered for phrase in reject_phrases):
        return False
    if ". " in cleaned and len(cleaned.split()) > 8:
        return False
    if cleaned.count(",") > 3:
        return False
    return bool(PERSON_NAME_RE.match(cleaned))


def preserve_title_page_line(value: str) -> str:
    """Normalize whitespace only; do not insert colons or re-title-case."""
    cleaned = normalize_text(value).strip().strip(".,;")
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_book_title(value: str) -> str:
    cleaned = normalize_text(value).strip().strip(".,;")
    cleaned = EDITION_SUFFIX_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s*:\s*", ": ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _title_case_catalog_line(cleaned)


def _title_case_catalog_line(value: str) -> str:
    parts = re.split(r"\s*:\s*", value, maxsplit=1)
    title = parts[0].strip()
    subtitle = parts[1].strip() if len(parts) > 1 else ""

    def _cap(segment: str) -> str:
        words = segment.split()
        if not words:
            return segment
        capped: list[str] = []
        for index, word in enumerate(words):
            lower = word.lower()
            if index > 0 and lower in TITLE_SMALL_WORDS:
                capped.append(lower)
            elif word.isupper() and len(word) > 2:
                capped.append(word.capitalize())
            else:
                capped.append(word[:1].upper() + word[1:] if word else word)
        return " ".join(capped)

    title_cased = _cap(title)
    if subtitle:
        subtitle = _loc_title_text_before_author_slash(subtitle)
        subtitle = EDITION_SUFFIX_RE.sub("", subtitle).strip()
        return f"{title_cased}: {_cap(subtitle)}"
    return title_cased


def _block_dominant_font_size(block) -> float:
    sizes = [span.size for line in block.lines for span in line.spans if span.size]
    return max(sizes) if sizes else 0.0


def line_looks_like_subject_name_list(line: str) -> bool:
    """Title-page line listing people (e.g. poets) rather than the book author."""
    stripped = normalize_text(line).strip()
    if not stripped or stripped.count(",") < 1:
        return False
    if " and " in stripped.lower():
        return True
    return stripped.count(",") >= 2


def _is_title_page_boilerplate_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if re.match(r"^isbn\b", stripped, re.IGNORECASE):
        return True
    skip_prefixes = (
        "published by",
        "copyright",
        "an imprint of",
        "www.",
        "http",
        "library of congress",
        "cataloging-in-publication",
        "all rights reserved",
    )
    if any(lowered.startswith(prefix) for prefix in skip_prefixes):
        return True
    if "©" in stripped and "copyright" in lowered:
        return True
    if STREET_ADDRESS_RE.search(stripped):
        return True
    return False


def _page_is_copyright_imprint_page(page) -> bool:
    text = " ".join((block.text or "") for block in page.blocks).lower()
    signals = sum(
        1
        for marker in (
            "copyright",
            "isbn",
            "published by",
            "all rights reserved",
            "library of congress",
        )
        if marker in text
    )
    return signals >= 2 and _page_word_count(page) > 40


def _candidate_title_page_numbers(raw: ExtractionResult, scan_limit: int = 12) -> list[int]:
    """Title pages often follow copyright (e.g. page 4); scan early pages, skip imprint-only."""
    candidates: list[int] = []
    for page in sorted(raw.pages, key=lambda p: p.page_number):
        if page.page_number > scan_limit:
            break
        if _page_is_copyright_imprint_page(page):
            continue
        if _page_word_count(page) > 120:
            continue
        has_title_like = False
        for block in page.blocks:
            block_text = _block_text_as_printed_line(block.text or "")
            if block_text and is_valid_book_title(block_text) and not _is_title_page_boilerplate_line(
                block_text
            ):
                has_title_like = True
                break
        if has_title_like:
            candidates.append(page.page_number)
    if candidates:
        return candidates
    return [page.page_number for page in sorted(raw.pages, key=lambda p: p.page_number)[:4]]


def _block_text_as_printed_line(block_text: str) -> str:
    """Join soft line breaks inside one typographic block; do not insert punctuation."""
    parts = [line.strip() for line in block_text.splitlines() if line.strip()]
    if not parts:
        return ""
    return preserve_title_page_line(" ".join(parts))


def _ordered_title_page_paragraphs(raw: ExtractionResult) -> list[str]:
    """Each title-page text block is one typographic paragraph."""
    paragraphs: list[str] = []
    for page_number in _candidate_title_page_numbers(raw):
        page = next((p for p in raw.pages if p.page_number == page_number), None)
        if page is None:
            continue
        for block in sorted(page.blocks, key=lambda b: b.bbox[1]):
            block_line = _block_text_as_printed_line(block.text or "")
            if not block_line or _is_title_page_boilerplate_line(block_line):
                continue
            paragraphs.append(block_line)
    return paragraphs


def _paragraph_is_subtitle_candidate(paragraph: str, title: str) -> bool:
    """Second title-page paragraph describing the work (not author/edition boilerplate)."""
    body = EDITION_SUFFIX_RE.sub("", paragraph).strip()
    if not body or body.casefold() == title.casefold():
        return False
    if _is_title_page_boilerplate_line(body):
        return False
    if line_looks_like_subject_name_list(body):
        return True
    author_only = normalize_book_author_name(body)
    if author_only and is_plausible_book_author_name(author_only):
        return False
    return len(body.split()) >= 2


def extract_title_page_triplet(
    raw: ExtractionResult,
) -> tuple[str | None, str | None, str | None]:
    """
    Title page paragraphs: first = title, second = subtitle when present, then author.
    """
    paragraphs = _ordered_title_page_paragraphs(raw)
    title_index: int | None = None
    title: str | None = None
    for index, paragraph in enumerate(paragraphs):
        line_clean = EDITION_SUFFIX_RE.sub("", paragraph).strip()
        if line_looks_like_subject_name_list(line_clean):
            continue
        if not is_valid_book_title(line_clean):
            continue
        title = preserve_title_page_line(line_clean)
        title_index = index
        break
    if title is None or title_index is None:
        return None, None, None

    subtitle: str | None = None
    author: str | None = None
    if title_index + 1 < len(paragraphs):
        second = paragraphs[title_index + 1]
        if _paragraph_is_subtitle_candidate(second, title):
            subtitle = preserve_title_page_line(EDITION_SUFFIX_RE.sub("", second).strip())
    author_start = title_index + (2 if subtitle else 1)
    for scan in range(author_start, min(title_index + 6, len(paragraphs))):
        candidate = normalize_book_author_name(paragraphs[scan])
        if candidate and is_plausible_book_author_name(candidate):
            author = candidate
            break

    return title, subtitle, author


def _publisher_imprint_pages_text(raw: ExtractionResult, max_pages: int = 15) -> str:
    parts: list[str] = []
    markers = (
        "published by",
        "copyright",
        "isbn",
        "forbes",
        "unit a",
        "whitacre",
        "rowman",
        "littlefield",
    )
    for page in sorted(raw.pages, key=lambda p: p.page_number):
        if page.page_number > max_pages:
            break
        text = join_ordered_block_text(raw, page_number=page.page_number)
        lowered = text.lower()
        if any(marker in lowered for marker in markers):
            parts.append(text)
    return "\n".join(parts)


def _author_name_looks_like_title_fragment(name: str, title: str | None, subtitle: str | None) -> bool:
    """Reject author candidates that are really title/subtitle wording."""
    if line_looks_like_subject_name_list(name):
        return True
    lowered = name.casefold()
    for fragment in (title, subtitle):
        if not fragment:
            continue
        if lowered == fragment.casefold():
            return True
        words = [w for w in re.findall(r"[A-Za-z']+", name) if len(w) > 2]
        if len(words) >= 3 and all(w.casefold() in fragment.casefold() for w in words):
            return True
    return False


def _resolve_book_author(
    raw: ExtractionResult,
    *,
    title_page_author: str | None,
    book_title: str | None = None,
    book_subtitle: str | None = None,
) -> str | None:
    """About-the-Author opener is authoritative when a bio is present."""
    bio_name = extract_author_name_from_about_blurb(raw)
    bio_author = normalize_book_author_name(bio_name or "") if bio_name else None
    if bio_author and not _author_name_looks_like_title_fragment(bio_author, book_title, book_subtitle):
        return bio_author

    title_author = normalize_book_author_name(title_page_author or "") if title_page_author else None
    if title_author and _author_name_looks_like_title_fragment(title_author, book_title, book_subtitle):
        title_author = None
    if title_author and is_plausible_book_author_name(title_author):
        return title_author
    return bio_author


def extract_isbn_list(text: str) -> list[str]:
    return [value for value, _qual in extract_isbn_entries(text)]


def extract_copyright_holder(text: str) -> str | None:
    match = COPYRIGHT_BY_HOLDER_RE.search(text)
    if not match:
        return None
    holder = normalize_text(match.group(1)).strip().rstrip(".,;")
    if not holder or len(holder) > 120:
        return None
    return holder


def extract_published_by_trade_name(text: str) -> str | None:
    pub_match = re.search(r"Published by\s+([^\n.]+)", text, re.IGNORECASE)
    if not pub_match:
        return None
    candidate = normalize_text(pub_match.group(1)).strip().rstrip(".,;")
    if not candidate or "imprint" in candidate.lower():
        return None
    return candidate


def extract_publisher_parent_company(text: str) -> str | None:
    """Parent publisher from ``An imprint of …`` (full legal name when present)."""
    imprint = IMPRINT_OF_RE.search(text)
    if imprint:
        name = normalize_text(imprint.group(1)).strip().rstrip(".,;")
        if name:
            return name.replace(" and ", " & ")
    for marker in PUBLISHER_MARKERS:
        if marker.lower() in text.lower():
            return marker.replace(" and ", " & ")
    return None


def extract_publisher_from_imprint(text: str) -> str | None:
    """Backward-compatible alias for parent publisher company."""
    return extract_publisher_parent_company(text)


def _line_looks_like_author_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.match(r"^by\s+", stripped, re.IGNORECASE):
        return True
    letters = [c for c in stripped if c.isalpha()]
    if stripped.isupper() and 2 <= len(stripped.split()) <= 6 and letters:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.85:
            return True
    return False


def _page_word_count(page) -> int:
    return sum(len((block.text or "").split()) for block in page.blocks)


def _loc_title_text_before_author_slash(title_segment: str) -> str:
    """LoC ``Title / Author`` — keep text before the author slash (preserve ``:`` in title)."""
    segment = title_segment.strip()
    if " / " in segment:
        segment = segment.split(" / ", 1)[0].strip()
    elif "/" in segment:
        segment = segment.split("/", 1)[0].strip()
    segment = segment.strip().strip(".,;")
    segment = re.sub(r"\s+", " ", segment).strip()
    return segment


def _strip_title_author_slash_suffix(title: str) -> str:
    """Remove trailing ``/ Author`` if it survived normalization (LoC cataloging)."""
    return _loc_title_text_before_author_slash(title)


def extract_title_from_loc_cip(raw_text: str) -> str | None:
    loc_match = _loc_cip_match(raw_text)
    if not loc_match:
        return None
    raw_title = _loc_title_text_before_author_slash(loc_match.group(1))
    title = _strip_title_author_slash_suffix(normalize_book_title(raw_title))
    return title if is_valid_book_title(title) else None


def extract_title_from_title_page(raw: ExtractionResult) -> str | None:
    best: tuple[float, str] | None = None
    for page in sorted(raw.pages, key=lambda p: p.page_number):
        if page.page_number > 3:
            break
        if _page_word_count(page) > 120:
            continue

        block_lines: list[tuple[str, float, float]] = []
        for block in sorted(page.blocks, key=lambda b: b.bbox[1]):
            font_size = _block_dominant_font_size(block)
            for line in (block.text or "").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if re.match(r"^ISBN\b", stripped, re.IGNORECASE):
                    continue
                if _line_looks_like_author_line(stripped):
                    continue
                if is_rejected_book_title_candidate(stripped) and ":" not in stripped:
                    continue
                block_lines.append((stripped, font_size, block.bbox[1]))

        if not block_lines:
            continue

        block_lines.sort(key=lambda item: (-item[1], item[2]))
        primary_lines = [text for text, size, _y in block_lines if size > 0][:4]
        if not primary_lines:
            primary_lines = [text for text, _, _ in block_lines[:4]]

        for index, line in enumerate(primary_lines):
            line_clean = EDITION_SUFFIX_RE.sub("", line).strip()
            if ":" in line_clean and is_valid_book_title(line_clean):
                candidate = preserve_title_page_line(line_clean)
                score = 5.0 + _block_dominant_font_size(page.blocks[0] if page.blocks else None)
                if best is None or score > best[0]:
                    best = (score, candidate)
                continue
            if is_valid_book_title(line_clean):
                candidate = preserve_title_page_line(line_clean)
                score = 4.5 + _block_dominant_font_size(page.blocks[0] if page.blocks else None)
                if best is None or score > best[0]:
                    best = (score, candidate)
            if index + 1 < len(primary_lines):
                next_line = EDITION_SUFFIX_RE.sub("", primary_lines[index + 1]).strip()
                if line_looks_like_subject_name_list(next_line):
                    candidate = preserve_title_page_line(line_clean)
                    score = 6.5
                    if best is None or score > best[0]:
                        best = (score, candidate)
                    break

    return best[1] if best else None


def _score_copyright_fallback_title(title: str) -> float:
    score = 0.0
    words = title.split()
    if ":" in title:
        score += 4.0
    if 4 <= len(words) <= 18:
        score += 2.0
    if 20 <= len(title) <= 140:
        score += 2.0
    if re.search(r"[a-z]", title) and re.search(r"[A-Z]", title):
        score += 1.0
    if STREET_ADDRESS_RE.search(title):
        score -= 20.0
    lowered = title.lower()
    if any(phrase in lowered for phrase in COPYRIGHT_TITLE_BOILERPLATE):
        score -= 20.0
    if len(title) > 160:
        score -= 5.0
    return score


def extract_title_copyright_fallback(raw_text: str) -> str | None:
    candidates: list[str] = []
    for line in re.split(r"[\n\r]+", raw_text):
        stripped = line.strip()
        if ":" not in stripped:
            continue
        catalog_match = CATALOG_LINE_RE.match(stripped)
        if catalog_match:
            candidates.append(normalize_book_title(catalog_match.group(1).strip()))
            continue
        if "/" in stripped and re.search(r"\d{4}-", stripped):
            continue
        candidate = normalize_book_title(stripped)
        if is_valid_book_title(candidate):
            candidates.append(candidate)

    for match in CATALOG_INLINE_RE.finditer(raw_text):
        candidate = normalize_book_title(match.group(1).strip())
        if is_valid_book_title(candidate):
            candidates.append(candidate)

    if not candidates:
        return None
    ranked = sorted(
        (( _score_copyright_fallback_title(c), c) for c in candidates),
        key=lambda item: item[0],
        reverse=True,
    )
    if ranked[0][0] < 1.0:
        return None
    return ranked[0][1]


def extract_book_title(raw_text: str, raw: ExtractionResult) -> str | None:
    """Priority: LOC/CIP block, title page, validated copyright fallback."""
    title = extract_title_from_loc_cip(raw_text)
    if title:
        return title

    triplet_title, triplet_subtitle, _triplet_author = extract_title_page_triplet(raw)
    if triplet_title and triplet_subtitle:
        return _strip_title_author_slash_suffix(triplet_title)

    title = extract_title_from_title_page(raw)
    if title:
        return _strip_title_author_slash_suffix(title)

    fallback = extract_title_copyright_fallback(raw_text)
    if fallback:
        return _strip_title_author_slash_suffix(fallback)
    return None


def _title_candidates_from_text(raw_text: str, raw: ExtractionResult | None = None) -> list[str]:
    """Backward-compatible helper for tests/debug."""
    if raw is None:
        title = extract_title_from_loc_cip(raw_text) or extract_title_copyright_fallback(raw_text)
        return [title] if title else []
    title = extract_book_title(raw_text, raw)
    return [title] if title else []


def _loc_cip_match(raw_text: str) -> re.Match[str] | None:
    collapsed = re.sub(r"\s+", " ", raw_text).strip()
    return LOC_CIP_RECORD_RE.search(collapsed)


def _invert_loc_surname_first(surname: str, given: str) -> str | None:
    given_clean = re.sub(r"\s+", " ", given).strip().rstrip(",")
    if not surname or not given_clean:
        return None
    return normalize_book_author_name(f"{given_clean} {surname.strip()}")


def _extract_author_from_loc_cip(raw_text: str) -> str | None:
    loc_match = _loc_cip_match(raw_text)
    if not loc_match:
        return None
    slash_author = normalize_book_author_name(loc_match.group(2).strip())
    if slash_author:
        return slash_author
    head = loc_match.group(0)
    surname_match = re.match(
        r"(?is)^\s*([A-Za-z'\-]+)\s*,\s*([A-Za-z.'\-\s]+?)\s*,?\s*\d{4}-",
        re.sub(r"\s+", " ", head),
    )
    if surname_match:
        return _invert_loc_surname_first(surname_match.group(1), surname_match.group(2))
    return None


def _extract_author_from_text(raw_text: str, normalized: str) -> str | None:
    loc_author = _extract_author_from_loc_cip(raw_text)
    if loc_author:
        return loc_author

    for line in re.split(r"[\n\r]+", raw_text):
        stripped = line.strip()
        catalog_match = CATALOG_LINE_RE.match(stripped)
        if catalog_match:
            author = catalog_match.group(2).strip().rstrip(",")
            author = normalize_book_author_name(author)
            if author:
                return author

    for match in CATALOG_INLINE_RE.finditer(raw_text):
        author = normalize_book_author_name(match.group(2).strip())
        if author:
            return author

    copy_match = COPYRIGHT_BY_AUTHOR_RE.search(normalized)
    if copy_match:
        author = normalize_book_author_name(copy_match.group(1))
        if author:
            return author

    by_match = BY_AUTHOR_RE.search(normalized)
    if by_match:
        author = normalize_book_author_name(by_match.group(1))
        if author:
            return author

    return None


def _extract_metadata_from_raw(raw: ExtractionResult) -> BookExtractionContext:
    front_text = _front_matter_pages_text(raw, max_pages=10)
    early_text = _early_pages_text(raw, max_pages=25)
    raw_text = f"{front_text}\n{early_text}"
    normalized = normalize_text(raw_text)

    isbn_entries = extract_isbn_entries(normalized)
    isbns = [value for value, _qual in isbn_entries]
    isbn = select_primary_isbn(isbn_entries)
    isbn_roles = tuple(
        (value, role)
        for value, qual in isbn_entries
        if (role := role_from_isbn_qualifier(qual))
    )

    year = None
    year_match = COPYRIGHT_YEAR_RE.search(normalized)
    if year_match:
        year = int(year_match.group(1))

    triplet_title, triplet_subtitle, triplet_author = extract_title_page_triplet(raw)
    title = extract_book_title(raw_text, raw)
    if triplet_title:
        title = triplet_title
    subtitle = triplet_subtitle

    author = _resolve_book_author(
        raw,
        title_page_author=triplet_author,
        book_title=title,
        book_subtitle=subtitle,
    )
    if not author:
        author = _extract_author_from_text(raw_text, normalized)
    if author and line_looks_like_subject_name_list(author):
        author = None

    copyright_holder = extract_copyright_holder(raw_text)
    trade_name = extract_published_by_trade_name(raw_text)
    publisher_parent = extract_publisher_parent_company(raw_text)
    publisher = publisher_parent or trade_name

    return BookExtractionContext(
        is_book=True,
        publication_document_type="book",
        title=title,
        subtitle=subtitle,
        author=author,
        publisher=publisher,
        publisher_imprint=trade_name,
        publisher_trade_name=trade_name,
        author_blurb=extract_about_the_author_blurb(raw),
        publisher_addresses=tuple(
            extract_publisher_addresses(_publisher_imprint_pages_text(raw) or raw_text)
        ),
        year=year,
        isbn=isbn,
        isbns=tuple(isbns),
        isbn_roles=isbn_roles,
        copyright_holder=copyright_holder,
    )


def detect_book_document(raw: ExtractionResult) -> BookExtractionContext:
    """Return book context when PDF looks like a book rather than a research paper."""
    page_count = len(raw.pages)
    early = _early_pages_text(raw, max_pages=25)
    sample = _full_text_sample(raw)
    scan_blob = f"{early}\n{sample[:40_000]}".lower()

    has_isbn = bool(ISBN_RE.search(scan_blob))
    has_lcc = "library of congress" in scan_blob or "cataloging-in-publication" in scan_blob
    has_rights = "all rights reserved" in scan_blob
    has_publisher = any(marker.lower() in scan_blob for marker in PUBLISHER_MARKERS)
    has_chapter_structure = bool(SPELLED_CHAPTER_MARKER_RE.search(sample)) or bool(
        re.search(r"\b(?:CHAPTER|Chapter)\s+(?:\d+|ONE|TWO|THREE)\b", sample, re.I)
    )
    has_long_form = page_count >= 80
    page1_text = join_ordered_block_text(raw, page_number=1) if raw.pages else ""
    has_research_front = bool(
        re.search(r"\bABSTRACT\b", page1_text, re.IGNORECASE)
        or re.search(r"\bKEYWORDS\b", page1_text, re.IGNORECASE)
        or re.search(r"IEEE\s", early, re.IGNORECASE)
        or re.search(r"Corresponding author:", early, re.IGNORECASE)
    )

    signals = [
        has_isbn,
        has_lcc,
        has_rights,
        has_publisher,
        has_chapter_structure,
        has_long_form,
        not has_research_front,
    ]
    signal_count = sum(1 for s in signals if s)
    if signal_count < 2:
        if page_count >= 80 and has_chapter_structure and not has_research_front:
            return _extract_metadata_from_raw(raw)
        return BookExtractionContext(is_book=False, publication_document_type="research_paper")

    return _extract_metadata_from_raw(raw)
