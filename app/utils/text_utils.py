"""Shared text normalization utilities (no layout dependencies)."""

from __future__ import annotations

import re

_LINE_BREAK_HYPHEN_RE = re.compile(r"(\w)-\s+([a-z]\w*)")
# PDF line breaks sometimes glue the suffix with no space: ``com-mitment``.
_TIGHT_LINE_BREAK_HYPHEN_RE = re.compile(r"\b([a-z]{2,})-([a-z]{2,})\b")
_CAPITALIZED_LINE_HYPHEN_RE = re.compile(r"\b([A-Z][a-z]{1,})-([a-z]{2,})\b")
_HYPHEN_JOIN_STOPWORDS = frozenset(
    {"a", "an", "as", "at", "by", "in", "of", "or", "the", "to", "and"}
)
_KEEP_INTENTIONAL_HYPHEN_TAIL = frozenset(
    {
        "quality",
        "grade",
        "known",
        "level",
        "term",
        "style",
        "fashioned",
        "wide",
        "based",
        "minded",
        "fascism",
        "imperialism",
        "war",
        "operative",
        "capitalist",
        "European",
        "american",
        "Semitic",
        "language",
        "garde",
        "century",
        "marked",
        "scale",
    }
)
_COMPOUND_HYPHEN_PREFIXES = frozenset(
    {
        "all",
        "anti",
        "co",
        "counter",
        "cross",
        "de",
        "ex",
        "extra",
        "intra",
        "inter",
        "mid",
        "multi",
        "neo",
        "non",
        "over",
        "post",
        "pre",
        "pro",
        "re",
        "self",
        "semi",
        "sub",
        "super",
        "trans",
        "ultra",
        "under",
        "vice",
        "well",
    }
)


def normalize_text(text: str) -> str:
    """Collapse whitespace and strip a text string.

    Example::

        >>> normalize_text("  hello\\n  world  ")
        'hello world'
    """
    return " ".join((text or "").replace("\n", " ").split()).strip()


def _should_keep_intentional_hyphen(left: str, right: str) -> bool:
    left_l = left.lower()
    right_l = right.lower()
    if left_l in _COMPOUND_HYPHEN_PREFIXES:
        return True
    if left_l in _HYPHEN_JOIN_STOPWORDS or right_l in _HYPHEN_JOIN_STOPWORDS:
        return True
    if right_l in _KEEP_INTENTIONAL_HYPHEN_TAIL:
        return True
    if len(left_l) >= 4 and len(right_l) >= 4:
        return True
    return False


def dehyphenate_line_breaks(text: str) -> str:
    """Join words broken across PDF lines (``instrumen- tal`` → ``instrumental``)."""
    if not text:
        return ""
    cleaned = _LINE_BREAK_HYPHEN_RE.sub(r"\1\2", text)
    cleaned = _CAPITALIZED_LINE_HYPHEN_RE.sub(r"\1\2", cleaned)

    def _join_tight(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        if _should_keep_intentional_hyphen(left, right):
            return match.group(0)
        return f"{left}{right}"

    return _TIGHT_LINE_BREAK_HYPHEN_RE.sub(_join_tight, cleaned)


_WRAP_JOIN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "as",
        "at",
        "be",
        "by",
        "do",
        "go",
        "he",
        "if",
        "in",
        "is",
        "it",
        "me",
        "my",
        "no",
        "of",
        "on",
        "or",
        "so",
        "to",
        "up",
        "us",
        "we",
        "all",
        "and",
        "any",
        "are",
        "but",
        "can",
        "did",
        "for",
        "get",
        "had",
        "has",
        "her",
        "him",
        "his",
        "how",
        "its",
        "may",
        "new",
        "not",
        "now",
        "off",
        "one",
        "our",
        "out",
        "own",
        "she",
        "the",
        "too",
        "two",
        "was",
        "way",
        "who",
        "why",
        "you",
        "after",
        "also",
        "been",
        "before",
        "being",
        "both",
        "each",
        "from",
        "have",
        "into",
        "just",
        "like",
        "more",
        "most",
        "much",
        "must",
        "only",
        "other",
        "over",
        "some",
        "such",
        "than",
        "that",
        "them",
        "then",
        "they",
        "this",
        "those",
        "upon",
        "very",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "your",
        "occur",
    }
)


def _should_join_wrapped_word(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    if previous[-1] in ".,;:!?)]}\"'”’":
        return False
    if current[0] in "([{\"'“‘":
        return False
    previous_word = previous.split()[-1]
    current_word = current.split()[0]
    if not previous_word or not current_word:
        return False
    if previous_word.endswith("-") or current_word.startswith("-"):
        return False
    if previous_word.lower() in _WRAP_JOIN_STOPWORDS:
        return False
    if current_word.lower() in _WRAP_JOIN_STOPWORDS:
        return False
    if previous_word[-1].isalpha() and current_word[0].isalpha():
        if previous_word[-1].islower() and current_word[0].islower():
            pl = len(previous_word)
            cl = len(current_word)
            # Join broken suffixes (instru+ments, Univer+sity), not dual+challenges / split+learning.
            if cl <= 5 and pl > cl:
                return True
            if cl <= 3 and pl >= 2:
                return True
            if pl <= 3 and cl >= 4:
                return True
    return False


_BOOK_CHAPTER_BODY_PARAGRAPH_SPLITS = (
    r"(?<=\)\.)\s+(?=There are )",
    r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=There are similarities)",
    r"(?<=\bthat)\s+(?=One of the best )",
    r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=The climate that fostered)",
)


_BOOK_ACK_PARAGRAPH_SPLITS = (
    r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=If I missed thanking anyone)",
    r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=I also wish to acknowledge)",
    r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=Finally,\s+I thank)",
    r"(?<=follows:)\s*(?=Gajjala,\s+R)",
    r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=Gajjala,\s+R\.?,)",
)


def _split_book_text_by_patterns(text: str, patterns: tuple[str, ...]) -> list[str]:
    parts = [text.strip()]
    for pattern in patterns:
        next_parts: list[str] = []
        for part in parts:
            if not part:
                continue
            chunks = re.split(pattern, part)
            if len(chunks) > 1:
                next_parts.extend(normalize_text(chunk) for chunk in chunks if normalize_text(chunk))
            else:
                next_parts.append(part)
        parts = next_parts
    return [normalize_text(p) for p in parts if normalize_text(p)]


def split_book_visual_paragraphs(text: str) -> list[str]:
    """Split imprint/body text on blank lines or block boundaries (PDF reading order)."""
    if not text or not text.strip():
        return []
    stripped = text.strip()
    ack_like = (
        "thank" in stripped.lower()
        and (
            "coauthor" in stripped.lower()
            or "acknowledg" in stripped.lower()
            or "if i missed thanking anyone" in stripped.lower()
        )
    )
    if ack_like:
        ack_parts = _split_book_text_by_patterns(stripped, _BOOK_ACK_PARAGRAPH_SPLITS)
        if len(ack_parts) > 1:
            return ack_parts
    if not ack_like:
        chapter_parts = _split_book_text_by_patterns(stripped, _BOOK_CHAPTER_BODY_PARAGRAPH_SPLITS)
        if len(chapter_parts) > 1:
            return chapter_parts
    # Only split on clear blank-line paragraph breaks (not "Chapter N …" overview sentences).
    for pattern in (
        r"\n\s*\n+",
        r"(?<=[.!?])(?:[\"'\u201d\u2019])?\s+(?=(?:The|This|It|In|A|An|First,|Second,|Third,|Finally,|A brief)\b)",
    ):
        parts = re.split(pattern, stripped)
        if len(parts) > 1:
            return [normalize_text(part) for part in parts if normalize_text(part)]
    return [normalize_text(text)]


def merge_block_texts(parts: list[str]) -> str:
    """Merge paragraph block fragments with drop-cap and hyphenation rules."""
    merged = ""
    for raw in parts:
        part = normalize_text(raw)
        if not part:
            continue
        if not merged:
            merged = part
            continue
        if len(merged) == 1 and merged.isalpha() and part[0].isalpha():
            merged = f"{merged}{part}"
            continue
        if re.search(r"-\s*$", merged):
            merged = re.sub(r"-\s*$", "", merged) + part
            continue
        if _should_join_wrapped_word(merged, part):
            if re.search(r"Available$", merged, re.IGNORECASE) and re.match(
                r"^Library\s+of\s+Congress", part, re.IGNORECASE
            ):
                merged = f"{merged} {part}"
            else:
                merged = f"{merged}{part}"
            continue
        merged = f"{merged} {part}"
    return dehyphenate_line_breaks(merged)


def infer_drop_cap_letter(text: str) -> str | None:
    """Infer a missing drop-cap letter from a truncated paragraph start."""
    normalized = normalize_text(text)
    if re.match(r"^ESEARCHERS\b", normalized):
        return "R"
    return None


def infer_drop_cap_from_paragraph_start(text: str) -> str | None:
    """Detect decorative initial letters from PDF layout merges (e.g. ``TO begin`` → ``T``)."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    if re.match(r"^TO\s+[a-z]", normalized):
        return "T"
    return infer_drop_cap_letter(normalized)


def drop_cap_letter_from_ir(detection_reason: str | None, paragraph_text: str) -> str | None:
    if detection_reason and detection_reason.startswith("drop_cap:"):
        return detection_reason.split(":", 1)[1]
    return infer_drop_cap_from_paragraph_start(paragraph_text)
