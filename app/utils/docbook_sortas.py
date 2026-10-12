"""Derive DocBook ``sortas`` from the same ``<title>`` text (never another book)."""

from __future__ import annotations

import re
import unicodedata

_LEADING_ARTICLE_RE = re.compile(r"^(?:A|An|The)\s+", re.IGNORECASE)
_LEADING_DIGITS_RE = re.compile(r"^(\d+)\b")

_ONES = (
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)


def _strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _int_to_english_words(value: int) -> str:
    if value < 0:
        return str(value)
    if value < 20:
        return _ONES[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        if ones == 0:
            return _TENS[tens]
        return f"{_TENS[tens]}-{_ONES[ones]}"
    if value < 1000:
        hundreds, remainder = divmod(value, 100)
        head = f"{_ONES[hundreds]} Hundred"
        if remainder == 0:
            return head
        return f"{head} {_int_to_english_words(remainder)}"
    if value < 10000:
        thousands, remainder = divmod(value, 1000)
        head = f"{_int_to_english_words(thousands)} Thousand"
        if remainder == 0:
            return head
        return f"{head} {_int_to_english_words(remainder)}"
    return str(value)


def _four_digit_title_number(value: int) -> str:
    if 1000 <= value <= 9999:
        high = value // 100
        low = value % 100
        left = _int_to_english_words(high)
        right = _int_to_english_words(low).replace(" ", "-")
        return f"{left} {right}"
    return _int_to_english_words(value)


def _replace_leading_digits(text: str) -> str:
    match = _LEADING_DIGITS_RE.match(text)
    if not match:
        return text
    digits = match.group(1)
    try:
        number = int(digits)
        words = _four_digit_title_number(number) if len(digits) == 4 else _int_to_english_words(number)
    except ValueError:
        return text
    rest = text[match.end() :].lstrip()
    if rest:
        return f"{words} {rest}"
    return words


def compute_sortas_from_title(title: str) -> str | None:
    """``sortas`` equals the title text after dropping a leading A/An/The only."""
    from app.utils.book_title_dedup import collapse_repeated_title_phrase

    cleaned = collapse_repeated_title_phrase(" ".join((title or "").split()))
    if not cleaned:
        return None
    sortas = _LEADING_ARTICLE_RE.sub("", cleaned).strip()
    return collapse_repeated_title_phrase(sortas) or None


def is_valid_sortas_for_title(title: str, sortas: str) -> bool:
    """Reject sortas that does not match the article-stripped title."""
    expected = compute_sortas_from_title(title)
    if not expected or not sortas:
        return False
    return " ".join(sortas.split()) == " ".join(expected.split())


def apply_sortas_to_title_element(title_element, title_text: str) -> None:
    """Set or remove ``sortas`` on a DocBook title element."""
    from app.utils.xml_text import sanitize_xml_text, set_lxml_attr

    cleaned_title = sanitize_xml_text(title_text)
    sortas = compute_sortas_from_title(cleaned_title)
    if sortas and is_valid_sortas_for_title(cleaned_title, sortas):
        set_lxml_attr(title_element, "sortas", sortas)
    elif "sortas" in title_element.attrib:
        del title_element.attrib["sortas"]
