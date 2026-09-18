"""Build structured IEEE JATS ``mixed-citation`` elements from plain reference text."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from app.utils.xml_text import set_lxml_text

_ACCESS_DATE_RE = re.compile(
    r"Accessed:\s*(?P<month>[A-Za-z]+\.?)\s*(?P<day>\d{1,2}),\s*(?P<year>\d{4})",
    re.IGNORECASE,
)
_QUOTED_TITLE_RE = re.compile(r"[“\"‘'](.+?)[”\"’']", re.DOTALL)
_VOLUME_RE = re.compile(r"\bvol\.\s*(\d+)", re.IGNORECASE)
_ISSUE_RE = re.compile(r"\bno\.\s*(\d+)", re.IGNORECASE)
_PAGES_RE = re.compile(r"\bpp\.\s*(\d+)\s*[–\-]\s*(\d+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_YEAR_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(?P<year>(19|20)\d{2})\b",
    re.IGNORECASE,
)
_AUTHOR_SPLIT_RE = re.compile(r",\s*(?=(?:[A-Z]\.|\band\b))")
_AUTHOR_INITIALS_RE = re.compile(
    r"^(?P<given>(?:[A-Z]\.\s*)+)(?P<surname>[A-Za-z][A-Za-z'\-]+(?:\s+[A-Za-z][A-Za-z'\-]+)*)$"
)
_CONF_LOC_RE = re.compile(r"\.\s*(?P<loc>[^:]+):\s*(?P<publisher>[^,]+),\s*(?P<year>(19|20)\d{2})", re.IGNORECASE)


def _ctx(ctx: dict[str, Any], field: str) -> dict[str, Any]:
    return {**ctx, "field": field}


def _set_tail(element: etree._Element, text: str) -> None:
    if text:
        element.tail = text


def _normalize_citation_text(text: str) -> str:
    normalized = " ".join(text.split())
    normalized = re.sub(r"Accessed:\s*", "Accessed: ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"Accessed:\s*([A-Za-z]+\.)\s*(\d{1,2}),\s*(\d{4})",
        r"Accessed: \1 \2, \3",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\.\s*\[Online\]", ". [Online]", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"\[Online\]\.\s*Available:\s*",
        "[Online]. Available: ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"Available:\s*(?=https?://)", "Available: ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(?<=[a-z]) (?=room/)", "-", normalized)
    return normalized.strip()


def _repair_url(url: str) -> str:
    cleaned = url.strip().rstrip(".,;")
    while re.search(r"(?<=[a-z]) (?=[a-z])", cleaned):
        cleaned = re.sub(r"(?<=[a-z]) (?=[a-z])", "-", cleaned)
    return cleaned


def _extract_url(text: str) -> tuple[str | None, str]:
    available = re.search(r"Available:\s*(.+)$", text, re.IGNORECASE)
    if available:
        candidate = available.group(1).strip().rstrip(".,;")
        if candidate.lower().startswith("http"):
            return _repair_url(candidate), text[: available.start()].strip()
    direct = re.search(r"(https?://\S+)", text, re.IGNORECASE)
    if direct:
        return _repair_url(direct.group(1)), text[: direct.start()].strip() + text[direct.end() :].strip()
    return None, text


def _classify_publication(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if re.search(r"https?://", lowered) or "[online]" in lowered or "accessed:" in lowered:
        return "book", "online"
    if re.search(r"\bin\s+proc\.|\bconf\.|\bconference\b", lowered):
        return "confproc", "print"
    return "periodical", "print"


def _strip_parsed_authors(blob: str, authors: list[tuple[str, str]]) -> str:
    remaining = blob
    for given, surname in authors:
        pattern = rf"{re.escape(given)}\s*{re.escape(surname)}"
        remaining = re.sub(pattern, "", remaining, count=1)
    remaining = re.sub(r"(?:^|[,;])\s*\band\b\s*", " ", remaining, flags=re.IGNORECASE)
    remaining = re.sub(r"^,\s*", "", remaining)
    return remaining.strip(" ,.")


def _authors_blob_before_title(text: str) -> str:
    title_match = _QUOTED_TITLE_RE.search(text)
    if title_match:
        return text[: title_match.start()].strip().rstrip(",")
    for pattern in (r"[“\"‘']", r"\bvol\.", r"\bpp\.", r"\bdoi:", r"\bin\s+Proc"):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return text[: match.start()].strip().rstrip(",")
    return text.strip().rstrip(",")


def _looks_like_author_part(part: str) -> bool:
    stripped = part.strip(" ,.")
    if not stripped:
        return False
    if stripped[0] in "“\"‘'":
        return False
    if stripped[0].islower():
        return False
    if _AUTHOR_INITIALS_RE.match(stripped):
        return True
    return bool(re.match(r"^[^,]+,\s*.+$", stripped))


def _parse_author_names(blob: str) -> list[tuple[str, str]]:
    blob = re.sub(r"\band\b", ",", blob, flags=re.IGNORECASE)
    parts = [part.strip(" ,.") for part in _AUTHOR_SPLIT_RE.split(blob) if part.strip(" ,.")]
    names: list[tuple[str, str]] = []
    for part in parts:
        if "et al" in part.lower():
            continue
        if not _looks_like_author_part(part):
            break
        match = _AUTHOR_INITIALS_RE.match(part.strip())
        if match:
            names.append((match.group("given").strip(), match.group("surname").strip()))
            continue
        comma_match = re.match(r"^(.+?),\s*(.+)$", part)
        if comma_match:
            names.append((comma_match.group(2).strip(), comma_match.group(1).strip()))
            continue
        break
    return names[:20]


def _append_person_group(citation: etree._Element, authors: list[tuple[str, str]], ctx: dict[str, Any]) -> None:
    if not authors:
        return
    group = etree.SubElement(citation, "person-group", {"person-group-type": "author"})
    for index, (given, surname) in enumerate(authors):
        name = etree.SubElement(group, "string-name")
        if given:
            given_el = etree.SubElement(name, "given-names")
            set_lxml_text(given_el, given, log_context=_ctx(ctx, "given-names"))
            _set_tail(given_el, " ")
        surname_el = etree.SubElement(name, "surname")
        set_lxml_text(surname_el, surname, log_context=_ctx(ctx, "surname"))
        if index < len(authors) - 1:
            _set_tail(name, ", ")
        elif len(authors) > 1:
            _set_tail(group, ", ")


def _append_simple_element(
    parent: etree._Element,
    tag: str,
    value: str,
    ctx: dict[str, Any],
    *,
    tail: str = "",
) -> etree._Element:
    element = etree.SubElement(parent, tag)
    set_lxml_text(element, value, log_context=_ctx(ctx, tag))
    if tail:
        _set_tail(element, tail)
    return element


def _build_online_book_citation(citation: etree._Element, text: str, ctx: dict[str, Any]) -> None:
    working = _normalize_citation_text(text)
    url, working = _extract_url(working)

    access_match = _ACCESS_DATE_RE.search(working)
    month = day = year = None
    if access_match:
        month = access_match.group("month")
        day = access_match.group("day")
        year = access_match.group("year")
        working = working[: access_match.start()] + working[access_match.end() :]

    working = re.sub(r"\[Online\]\.\s*Available:\s*", "", working, flags=re.IGNORECASE)
    working = re.sub(r"\[Online\]\.?", "", working, flags=re.IGNORECASE)
    working = re.sub(r"Available:\s*", "", working, flags=re.IGNORECASE)
    working = re.sub(r"Accessed:\s*", "", working, flags=re.IGNORECASE)
    working = " ".join(working.split()).strip(" .")

    org = ""
    source = ""
    if ". " in working:
        org, remainder = working.split(". ", 1)
        org = org.strip()
        source = remainder.strip(" .")
    else:
        org = working.strip()

    if org:
        collab = etree.SubElement(citation, "collab")
        set_lxml_text(collab, org, log_context=_ctx(ctx, "collab"))
        _set_tail(collab, ". ")

    if source:
        source_el = etree.SubElement(citation, "source")
        set_lxml_text(source_el, source, log_context=_ctx(ctx, "source"))
        if access_match:
            _set_tail(source_el, ". Accessed: ")
        elif url:
            _set_tail(source_el, ". [Online]. Available: ")

    if access_match:
        if month:
            month_el = etree.SubElement(citation, "month")
            set_lxml_text(month_el, month, log_context=_ctx(ctx, "month"))
            _set_tail(month_el, " ")
        if day:
            day_el = etree.SubElement(citation, "day")
            set_lxml_text(day_el, day, log_context=_ctx(ctx, "day"))
            _set_tail(day_el, ", ")
        if year:
            year_el = etree.SubElement(citation, "year")
            set_lxml_text(year_el, year, log_context=_ctx(ctx, "year"))
            _set_tail(year_el, ". [Online]. Available: ")

    if url:
        uri_el = etree.SubElement(citation, "uri")
        set_lxml_text(uri_el, url, log_context=_ctx(ctx, "uri"))


def _has_structured_citation_content(citation: etree._Element) -> bool:
    structured_tags = {
        "person-group",
        "article-title",
        "source",
        "collab",
        "uri",
        "volume",
        "issue",
        "fpage",
    }
    return any(citation.find(tag) is not None for tag in structured_tags)


def _build_periodical_citation(citation: etree._Element, text: str, ctx: dict[str, Any]) -> None:
    title_match = _QUOTED_TITLE_RE.search(text)
    authors_blob = _authors_blob_before_title(text)

    authors = _parse_author_names(authors_blob)
    _append_person_group(citation, authors, ctx)

    last_element: etree._Element | None = citation.find("person-group")

    if title_match:
        if last_element is not None:
            _set_tail(last_element, "“")
        title_el = etree.SubElement(citation, "article-title")
        set_lxml_text(title_el, title_match.group(1).strip(), log_context=_ctx(ctx, "article-title"))
        _set_tail(title_el, ",” ")
        last_element = title_el
    else:
        remainder = _strip_parsed_authors(authors_blob, authors)
        if remainder and not _VOLUME_RE.search(remainder) and not _YEAR_RE.search(remainder):
            if last_element is not None:
                _set_tail(last_element, ", ")
            title_el = etree.SubElement(citation, "article-title")
            set_lxml_text(title_el, remainder, log_context=_ctx(ctx, "article-title"))
            _set_tail(title_el, ".")
            last_element = title_el

    source_match = re.search(
        r"(?:,\s*[”\"]\s*)?(?P<source>[A-Za-z][^,]+(?:J\.|Journal|Med\.|Clinicians|Cureus|Nature)[^,]*?)(?=,\s*vol\.|,\s*pp\.|,\s*\b(19|20)\d{2}\b|$)",
        text,
        re.IGNORECASE,
    )
    if source_match:
        source_el = etree.SubElement(citation, "source")
        set_lxml_text(source_el, source_match.group("source").strip(), log_context=_ctx(ctx, "source"))
        _set_tail(source_el, ", ")
        last_element = source_el

    vol_match = _VOLUME_RE.search(text)
    issue_match = _ISSUE_RE.search(text)
    pages_match = _PAGES_RE.search(text)

    if vol_match:
        if last_element is not None:
            _set_tail(last_element, "vol. ")
        volume_tail = ", no. " if issue_match else ", "
        volume_el = _append_simple_element(citation, "volume", vol_match.group(1), ctx, tail=volume_tail)
        last_element = volume_el

    if issue_match:
        if last_element is None:
            citation.text = (citation.text or "") + "no. "
        elif last_element.tag != "volume":
            _set_tail(last_element, "no. ")
        issue_tail = ", pp. " if pages_match else ", "
        issue_el = _append_simple_element(citation, "issue", issue_match.group(1), ctx, tail=issue_tail)
        last_element = issue_el

    if pages_match:
        if last_element is not None and last_element.tag not in {"volume", "issue"}:
            _set_tail(last_element, "pp. ")
        elif last_element is None:
            citation.text = (citation.text or "") + "pp. "
        fpage = _append_simple_element(citation, "fpage", pages_match.group(1), ctx)
        _set_tail(fpage, "–")
        lpage = _append_simple_element(citation, "lpage", pages_match.group(2), ctx, tail=", ")
        last_element = lpage

    month_year_match = _MONTH_YEAR_RE.search(text)
    year_match = _YEAR_RE.search(text)
    if month_year_match:
        month_el = etree.SubElement(citation, "month")
        set_lxml_text(month_el, month_year_match.group(1), log_context=_ctx(ctx, "month"))
        _set_tail(month_el, " ")
        year_el = etree.SubElement(citation, "year")
        set_lxml_text(year_el, month_year_match.group("year"), log_context=_ctx(ctx, "year"))
        _set_tail(year_el, ".")
    elif year_match:
        year_el = etree.SubElement(citation, "year")
        set_lxml_text(year_el, year_match.group(0), log_context=_ctx(ctx, "year"))
        _set_tail(year_el, ".")


def _build_confproc_citation(citation: etree._Element, text: str, ctx: dict[str, Any]) -> None:
    title_match = _QUOTED_TITLE_RE.search(text)
    authors_blob = _authors_blob_before_title(text)
    authors = _parse_author_names(authors_blob)
    _append_person_group(citation, authors, ctx)
    last_element: etree._Element | None = citation.find("person-group")

    if title_match:
        if last_element is not None:
            _set_tail(last_element, "“")
        title_el = etree.SubElement(citation, "article-title")
        set_lxml_text(title_el, title_match.group(1).strip(), log_context=_ctx(ctx, "article-title"))
        _set_tail(title_el, ",” in ")
        last_element = title_el

    proc_match = re.search(r"\bin\s+(?P<source>Proc\.[^,]+)", text, re.IGNORECASE)
    if proc_match:
        source_el = etree.SubElement(citation, "source")
        set_lxml_text(source_el, proc_match.group("source").strip(), log_context=_ctx(ctx, "source"))
        _set_tail(source_el, ". ")
        last_element = source_el

    loc_match = _CONF_LOC_RE.search(text)
    if loc_match:
        loc_el = etree.SubElement(citation, "conf-loc")
        set_lxml_text(loc_el, loc_match.group("loc").strip(), log_context=_ctx(ctx, "conf-loc"))
        _set_tail(loc_el, ": ")
        name_el = etree.SubElement(citation, "conf-name")
        set_lxml_text(name_el, loc_match.group("publisher").strip(), log_context=_ctx(ctx, "conf-name"))
        _set_tail(name_el, ", ")
        year_el = etree.SubElement(citation, "conf-date")
        set_lxml_text(year_el, loc_match.group("year"), log_context=_ctx(ctx, "conf-date"))
        _set_tail(year_el, ", ")
        last_element = year_el

    pages_match = _PAGES_RE.search(text)
    if pages_match:
        if last_element is not None:
            _set_tail(last_element, "pp. ")
        fpage = _append_simple_element(citation, "fpage", pages_match.group(1), ctx)
        _set_tail(fpage, "–")
        _append_simple_element(citation, "lpage", pages_match.group(2), ctx, tail=".")


def populate_structured_mixed_citation(
    citation: etree._Element,
    citation_text: str,
    *,
    log_context: dict[str, Any] | None = None,
) -> None:
    """Populate a ``mixed-citation`` element with structured JATS children."""
    text = _normalize_citation_text(citation_text.strip())
    ctx = log_context or {}
    if not text:
        return

    pub_type, pub_format = _classify_publication(text)
    citation.set("publication-type", pub_type)
    citation.set("publication-format", pub_format)

    if pub_type == "book" and pub_format == "online":
        _build_online_book_citation(citation, text, ctx)
    elif pub_type == "confproc":
        _build_confproc_citation(citation, text, ctx)
    else:
        _build_periodical_citation(citation, text, ctx)

    if not _has_structured_citation_content(citation):
        for child in list(citation):
            citation.remove(child)
        set_lxml_text(citation, text, log_context=_ctx(ctx, "citation"))
