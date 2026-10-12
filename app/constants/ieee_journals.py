"""Verified IEEE periodical identifiers for JATS ``journal-meta`` overlay."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ISSN_KEY_RE = re.compile(r"[^0-9x]")


@dataclass(frozen=True)
class IeeeJournalMeta:
    title: str
    ieee_id: str
    acronym: str
    coden: str
    issn_print: str
    issn_online: str
    filename_prefixes: tuple[str, ...] = ()
    title_aliases: tuple[str, ...] = ()
    header_patterns: tuple[str, ...] = ()


def normalize_journal_key(value: str) -> str:
    lowered = value.lower().strip()
    lowered = re.sub(r"[^\w\s-]", " ", lowered)
    return " ".join(lowered.split())


def _issn_key(value: str) -> str:
    return _ISSN_KEY_RE.sub("", value.lower())


def _record(
    *,
    title: str,
    ieee_id: str,
    acronym: str,
    coden: str,
    issn_print: str,
    issn_online: str,
    filename_prefixes: tuple[str, ...] = (),
    title_aliases: tuple[str, ...] = (),
    header_patterns: tuple[str, ...] = (),
) -> IeeeJournalMeta:
    return IeeeJournalMeta(
        title=title,
        ieee_id=ieee_id,
        acronym=acronym,
        coden=coden,
        issn_print=issn_print,
        issn_online=issn_online,
        filename_prefixes=filename_prefixes,
        title_aliases=title_aliases,
        header_patterns=header_patterns,
    )


_JOURNALS: tuple[IeeeJournalMeta, ...] = (
    _record(
        title="IEEE Access",
        ieee_id="0063500",
        acronym="ACCESS",
        coden="IAECCG",
        issn_print="2169-3536",
        issn_online="2169-3536",
        filename_prefixes=("access",),
        title_aliases=("ieee access",),
        header_patterns=(r"\bieee\s+access\b",),
    ),
    _record(
        title="IEEE Journal of Solid-State Circuits",
        ieee_id="0055700",
        acronym="JSSC",
        coden="IJSCBC",
        issn_print="0018-9200",
        issn_online="1558-173X",
        filename_prefixes=("jssc",),
        title_aliases=(
            "ieee journal of solid state circuits",
            "ieee j. solid-state circuits",
            "ieee j solid state circuits",
        ),
        header_patterns=(
            r"\bieee\s+journal\s+of\s+solid[- ]state\s+circuits\b",
            r"\bjournal\s+of\s+solid[- ]state\s+circuits\b",
        ),
    ),
    _record(
        title="IEEE Transactions on Consumer Electronics",
        ieee_id="0074700",
        acronym="TCE",
        coden="ITCEDA",
        issn_print="0098-3063",
        issn_online="1558-4127",
        filename_prefixes=("tce",),
        title_aliases=(
            "ieee transactions on consumer electronics",
            "ieee trans. consumer electronics",
            "ieee trans consumer electronics",
        ),
        header_patterns=(
            r"\bconsumer\s+electronics\b",
            r"\bieee\s+trans(?:actions)?\.?\s+on\s+consumer\b",
        ),
    ),
)

IEEE_JOURNALS_BY_KEY: dict[str, IeeeJournalMeta] = {}
ISSN_TO_JOURNAL: dict[str, IeeeJournalMeta] = {}
DOI_PREFIX_TO_JOURNAL: dict[str, IeeeJournalMeta] = {}
_ACRONYM_TO_JOURNAL: dict[str, IeeeJournalMeta] = {}
_HEADER_PATTERNS: list[tuple[re.Pattern[str], IeeeJournalMeta]] = []

for _journal in _JOURNALS:
    keys = {normalize_journal_key(_journal.title)}
    keys.update(normalize_journal_key(alias) for alias in _journal.title_aliases)
    for key in keys:
        IEEE_JOURNALS_BY_KEY[key] = _journal
    for issn in (_journal.issn_print, _journal.issn_online):
        ISSN_TO_JOURNAL[_issn_key(issn)] = _journal
    DOI_PREFIX_TO_JOURNAL[f"10.1109/{_journal.acronym.lower()}."] = _journal
    _ACRONYM_TO_JOURNAL[_journal.acronym.upper()] = _journal
    for pattern in _journal.header_patterns:
        _HEADER_PATTERNS.append((re.compile(pattern, re.I), _journal))


def all_journal_records() -> tuple[IeeeJournalMeta, ...]:
    return _JOURNALS


def record_by_acronym(acronym: str) -> IeeeJournalMeta | None:
    return _ACRONYM_TO_JOURNAL.get(acronym.upper())


def match_journal_in_text(text: str) -> IeeeJournalMeta | None:
    if not text:
        return None
    for pattern, record in _HEADER_PATTERNS:
        if pattern.search(text):
            return record
    normalized = normalize_journal_key(text)
    for key, record in IEEE_JOURNALS_BY_KEY.items():
        if key in normalized or normalized in key:
            return record
    return None


def lookup_ieee_journal(
    *,
    journal_title: str | None = None,
    doi: str | None = None,
    issn: str | None = None,
    source_filename: str | None = None,
) -> IeeeJournalMeta | None:
    if issn:
        record = ISSN_TO_JOURNAL.get(_issn_key(issn))
        if record:
            return record
    if journal_title:
        record = IEEE_JOURNALS_BY_KEY.get(normalize_journal_key(journal_title))
        if record:
            return record
        record = match_journal_in_text(journal_title)
        if record:
            return record
    if doi:
        lowered = doi.lower()
        for prefix, record in DOI_PREFIX_TO_JOURNAL.items():
            if lowered.startswith(prefix):
                return record
    if source_filename:
        lowered = source_filename.lower()
        stem = re.sub(r"\.(pdf|xml).*$", "", lowered, flags=re.I)
        prefix = re.split(r"[-_]", stem)[0]
        matches = [j for j in _JOURNALS if prefix in {p.lower() for p in j.filename_prefixes}]
        if len(matches) == 1:
            return matches[0]
    return None
