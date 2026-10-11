"""Known IEEE periodical identifiers for JATS ``journal-meta`` overlay."""

from __future__ import annotations

import re

from dataclasses import dataclass


@dataclass(frozen=True)
class IeeeJournalMeta:
    title: str
    ieee_id: str
    acronym: str
    coden: str
    issn_print: str
    issn_online: str


def _normalize_journal_key(value: str) -> str:
    return " ".join(value.lower().split())


IEEE_JOURNALS_BY_KEY: dict[str, IeeeJournalMeta] = {
    _normalize_journal_key("IEEE Access"): IeeeJournalMeta(
        title="IEEE Access",
        ieee_id="0063500",
        acronym="ACCESS",
        coden="IAECCG",
        issn_print="2169-3536",
        issn_online="2169-3536",
    ),
    _normalize_journal_key("IEEE Transactions on Consumer Electronics"): IeeeJournalMeta(
        title="IEEE Transactions on Consumer Electronics",
        ieee_id="0074700",
        acronym="TCE",
        coden="ITCEDA",
        issn_print="0098-3063",
        issn_online="1558-4127",
    ),
}

DOI_PREFIX_TO_KEY: dict[str, str] = {
    "10.1109/access.": _normalize_journal_key("IEEE Access"),
    "10.1109/tce.": _normalize_journal_key("IEEE Transactions on Consumer Electronics"),
}


def lookup_ieee_journal(
    *,
    journal_title: str | None = None,
    doi: str | None = None,
    source_filename: str | None = None,
) -> IeeeJournalMeta | None:
    if journal_title:
        record = IEEE_JOURNALS_BY_KEY.get(_normalize_journal_key(journal_title))
        if record:
            return record
    if doi:
        lowered = doi.lower()
        for prefix, key in DOI_PREFIX_TO_KEY.items():
            if lowered.startswith(prefix):
                return IEEE_JOURNALS_BY_KEY.get(key)
    if source_filename:
        lowered = source_filename.lower()
        if "access-" in lowered:
            return IEEE_JOURNALS_BY_KEY[_normalize_journal_key("IEEE Access")]
        if re.search(r"(?:^|[-_])tce[-_]", lowered) or lowered.startswith("tce-"):
            return IEEE_JOURNALS_BY_KEY[_normalize_journal_key("IEEE Transactions on Consumer Electronics")]
    return None
