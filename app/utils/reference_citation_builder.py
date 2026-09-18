"""Build structured IEEE JATS ``mixed-citation`` elements from plain reference text."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from app.utils.xml_text import set_lxml_text

_URL_RE = re.compile(r"(https?://\S+)")
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
_CONF_IN_RE = re.compile(r",\s*[“\"](.+?)[”\"],\s*in\s+", re.IGNORECASE | re.DOTALL)
_CONF_LOC_RE = re.compile(r"\.\s*(?P<loc>[^:]+):\s*(?P<publisher>[^,]+),\s*(?P<year>(19|20)\d{2})", re.IGNORECASE)


def _ctx(ctx: dict[str, Any], field: str) -> dict[str, Any]:
    return {**ctx, "field": field}


def _append_tail(element: etree._Element, text: str) -> None:
    if not text:
        return
    element.tail = (element.tail or "") + text


def _classify_publication(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if _URL_RE.search(text) or "[online]" in lowered or "accessed:" in lowered:
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


def _parse_author_names(blob: str) -> list[tuple[str, str]]:
    blob = re.sub(r"\band\b", ",", blob, flags=re.IGNORECASE)
    parts = [part.strip(" ,.") for part in _AUTHOR_SPLIT_RE.split(blob) if part.strip(" ,.")]
    names: list[tuple[str, str]] = []
    for part in parts:
        if "et al" in part.lower():
            continue
        match = _AUTHOR_INITIALS_RE.match(part.strip())
        if match:
            names.append((match.group("given").strip(), match.group("surname").strip()))
            continue
        comma_match = re.match(r"^(.+?),\s*(.+)$", part)
        if comma_match:
            names.append((comma_match.group(2).strip(), comma_match.group(1).strip()))
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
            _append_tail(given_el, " ")
        surname_el = etree.SubElement(name, "surname")
        set_lxml_text(surname_el, surname, log_context=_ctx(ctx, "surname"))
        if index < len(authors) - 1:
            _append_tail(name, ", ")
        elif len(authors) > 1:
            _append_tail(group, ", ")


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
        _append_tail(element, tail)
    return element


def _build_online_book_citation(citation: etree._Element, text: str, ctx: dict[str, Any]) -> None:
    working = text
    url_match = _URL_RE.search(working)
    url = url_match.group(1).rstrip(".,;") if url_match else None
    if url_match:
        working = working[: url_match.start()] + working[url_match.end() :]

    access_match = _ACCESS_DATE_RE.search(working)
    month = day = year = None
    if access_match:
        month = access_match.group("month")
        day = access_match.group("day")
        year = access_match.group("year")
        working = working[: access_match.start()] + working[access_match.end() :]

    working = re.sub(r"\[Online\]\.\s*Available:\s*", "", working, flags=re.IGNORECASE)
    working = re.sub(r"Accessed:\s*", "", working, flags=re.IGNORECASE)
    working = " ".join(working.split())

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
        _append_tail(collab, ". ")

    if source:
        source_el = etree.SubElement(citation, "source")
        set_lxml_text(source_el, source, log_context=_ctx(ctx, "source"))
        _append_tail(source_el, ". ")

    if access_match:
        _append_tail(citation, "Accessed: ")
        if month:
            month_el = etree.SubElement(citation, "month")
            set_lxml_text(month_el, month, log_context=_ctx(ctx, "month"))
            _append_tail(month_el, " ")
        if day:
            day_el = etree.SubElement(citation, "day")
            set_lxml_text(day_el, day, log_context=_ctx(ctx, "day"))
            _append_tail(day_el, ", ")
        if year:
            year_el = etree.SubElement(citation, "year")
            set_lxml_text(year_el, year, log_context=_ctx(ctx, "year"))
            _append_tail(year_el, ". [Online]. Available: ")
    elif url:
        _append_tail(citation, "[Online]. Available: ")

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
    authors_blob = text[: title_match.start()] if title_match else text
    authors_blob = authors_blob.strip().rstrip(",")

    authors = _parse_author_names(authors_blob)
    _append_person_group(citation, authors, ctx)

    if title_match:
        _append_tail(citation, "“")
        title_el = etree.SubElement(citation, "article-title")
        set_lxml_text(title_el, title_match.group(1).strip(), log_context=_ctx(ctx, "article-title"))
        _append_tail(title_el, ",” ")
    else:
        remainder = _strip_parsed_authors(authors_blob, authors)
        if remainder and not _VOLUME_RE.search(remainder) and not _YEAR_RE.search(remainder):
            if len(citation):
                _append_tail(citation, ", ")
            title_el = etree.SubElement(citation, "article-title")
            set_lxml_text(title_el, remainder, log_context=_ctx(ctx, "article-title"))
            _append_tail(title_el, ".")

    source_match = re.search(
        r"(?:,\s*[”\"]\s*)?(?P<source>[A-Za-z][^,]+(?:J\.|Journal|Med\.|Clinicians|Cureus|Nature)[^,]*?)(?=,\s*vol\.|,\s*pp\.|,\s*\b(19|20)\d{2}\b|$)",
        text,
        re.IGNORECASE,
    )
    if source_match:
        source_el = etree.SubElement(citation, "source")
        set_lxml_text(source_el, source_match.group("source").strip(), log_context=_ctx(ctx, "source"))
        _append_tail(source_el, ", ")

    vol_match = _VOLUME_RE.search(text)
    if vol_match:
        _append_tail(citation, "vol. ")
        _append_simple_element(citation, "volume", vol_match.group(1), ctx, tail=", ")

    issue_match = _ISSUE_RE.search(text)
    if issue_match:
        _append_tail(citation, "no. ")
        _append_simple_element(citation, "issue", issue_match.group(1), ctx, tail=", ")

    pages_match = _PAGES_RE.search(text)
    if pages_match:
        _append_tail(citation, "pp. ")
        fpage = _append_simple_element(citation, "fpage", pages_match.group(1), ctx)
        _append_tail(fpage, "–")
        _append_simple_element(citation, "lpage", pages_match.group(2), ctx, tail=", ")

    month_year_match = _MONTH_YEAR_RE.search(text)
    year_match = _YEAR_RE.search(text)
    if month_year_match:
        month_el = etree.SubElement(citation, "month")
        set_lxml_text(month_el, month_year_match.group(1), log_context=_ctx(ctx, "month"))
        _append_tail(month_el, " ")
        year_el = etree.SubElement(citation, "year")
        set_lxml_text(year_el, month_year_match.group("year"), log_context=_ctx(ctx, "year"))
        _append_tail(year_el, ".")
    elif year_match:
        year_el = etree.SubElement(citation, "year")
        set_lxml_text(year_el, year_match.group(0), log_context=_ctx(ctx, "year"))
        _append_tail(year_el, ".")


def _build_confproc_citation(citation: etree._Element, text: str, ctx: dict[str, Any]) -> None:
    title_match = _QUOTED_TITLE_RE.search(text)
    authors_blob = text[: title_match.start()] if title_match else text
    authors_blob = authors_blob.strip().rstrip(",")
    authors = _parse_author_names(authors_blob)
    _append_person_group(citation, authors, ctx)

    if title_match:
        _append_tail(citation, "“")
        title_el = etree.SubElement(citation, "article-title")
        set_lxml_text(title_el, title_match.group(1).strip(), log_context=_ctx(ctx, "article-title"))
        _append_tail(title_el, ",” in ")

    proc_match = re.search(r"\bin\s+(?P<source>Proc\.[^,]+)", text, re.IGNORECASE)
    if proc_match:
        source_el = etree.SubElement(citation, "source")
        set_lxml_text(source_el, proc_match.group("source").strip(), log_context=_ctx(ctx, "source"))
        _append_tail(source_el, ". ")

    loc_match = _CONF_LOC_RE.search(text)
    if loc_match:
        loc_el = etree.SubElement(citation, "conf-loc")
        set_lxml_text(loc_el, loc_match.group("loc").strip(), log_context=_ctx(ctx, "conf-loc"))
        _append_tail(loc_el, ": ")
        name_el = etree.SubElement(citation, "conf-name")
        set_lxml_text(name_el, loc_match.group("publisher").strip(), log_context=_ctx(ctx, "conf-name"))
        _append_tail(name_el, ", ")
        year_el = etree.SubElement(citation, "conf-date")
        set_lxml_text(year_el, loc_match.group("year"), log_context=_ctx(ctx, "conf-date"))
        _append_tail(year_el, ", ")

    pages_match = _PAGES_RE.search(text)
    if pages_match:
        _append_tail(citation, "pp. ")
        fpage = _append_simple_element(citation, "fpage", pages_match.group(1), ctx)
        _append_tail(fpage, "–")
        _append_simple_element(citation, "lpage", pages_match.group(2), ctx, tail=".")


def populate_structured_mixed_citation(
    citation: etree._Element,
    citation_text: str,
    *,
    log_context: dict[str, Any] | None = None,
) -> None:
    """Populate a ``mixed-citation`` element with structured JATS children."""
    text = citation_text.strip()
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
