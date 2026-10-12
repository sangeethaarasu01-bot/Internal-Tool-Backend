"""Resolve IEEE journal metadata from PDF evidence and a verified registry."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.constants.ieee_journals import (
    IeeeJournalMeta,
    all_journal_records,
    lookup_ieee_journal,
)

logger = logging.getLogger(__name__)

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;)]+", re.I)
ISSN_RE = re.compile(r"\b\d{4}-\d{3}[\dXx]\b")

EvidenceKind = str  # pdf_title | pdf_doi | pdf_issn | ir_journal_header | filename_prefix


@dataclass(frozen=True)
class JournalEvidence:
    journal_title: str | None = None
    doi: str | None = None
    issn: str | None = None
    source_filename: str | None = None
    ir_journal_header: str | None = None


@dataclass
class JournalResolutionResult:
    journal: IeeeJournalMeta | None = None
    journal_title: str | None = None
    evidence: list[tuple[EvidenceKind, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    template_mismatch: bool = False


def _filename_prefix_candidate(filename: str | None) -> str | None:
    if not filename:
        return None
    stem = re.sub(r"\.(pdf|xml).*$", "", filename, flags=re.I)
    stem = re.sub(r"[-_]?proof(\d+)?$", "", stem, flags=re.I)
    first = re.split(r"[-_]", stem.lower())[0]
    return first if first and len(first) >= 2 else None


def _match_by_filename_prefix(prefix: str) -> IeeeJournalMeta | None:
    matches: list[IeeeJournalMeta] = []
    for record in all_journal_records():
        if prefix in {p.lower() for p in record.filename_prefixes}:
            matches.append(record)
    if len(matches) == 1:
        return matches[0]
    return None


def _collect_issn(header: str) -> str | None:
    for match in ISSN_RE.finditer(header[:12000]):
        return match.group(0)
    return None


def collect_journal_evidence(
    *,
    header_text: str,
    ir: dict[str, Any] | None = None,
    source_filename: str | None = None,
    doi: str | None = None,
) -> JournalEvidence:
    title: str | None = None
    parsed_doi = doi
    if not parsed_doi:
        abstract_pos = header_text.upper().find("ABSTRACT")
        region = header_text[:abstract_pos] if abstract_pos > 0 else header_text[:8000]
        match = DOI_RE.search(region)
        if match:
            parsed_doi = match.group(0).rstrip(".;,)")

    from app.constants.ieee_journals import match_journal_in_text

    matched = match_journal_in_text(header_text)
    if matched:
        title = matched.title

    ir_header: str | None = None
    front = (ir or {}).get("front") or {}
    journal = front.get("journal_header")
    from app.utils.proof_pdf import is_author_queries_heading, is_plausible_journal_title_line

    if isinstance(journal, dict):
        ir_header = (journal.get("text") or "").strip()
        for item in journal.get("elements") or []:
            ir_header += str(item.get("value") or "")
        ir_header = ir_header.strip() or None
        if ir_header and (
            is_author_queries_heading(ir_header) or not is_plausible_journal_title_line(ir_header)
        ):
            ir_header = None
        if ir_header and not title:
            mapped = lookup_ieee_journal(journal_title=ir_header)
            if mapped:
                title = mapped.title

    if not title and source_filename:
        prefix = _filename_prefix_candidate(source_filename)
        if prefix:
            by_prefix = _match_by_filename_prefix(prefix)
            if by_prefix:
                title = by_prefix.title

    if not title:
        for line in header_text.splitlines():
            candidate = line.strip()
            if not candidate or candidate.upper() == "ABSTRACT":
                break
            if DOI_RE.search(candidate) or ISSN_RE.search(candidate):
                continue
            if is_plausible_journal_title_line(candidate):
                title = candidate
                break

    return JournalEvidence(
        journal_title=title,
        doi=parsed_doi,
        issn=_collect_issn(header_text),
        source_filename=source_filename,
        ir_journal_header=ir_header,
    )


def resolve_journal_metadata(evidence: JournalEvidence) -> JournalResolutionResult:
    """Resolve journal using registry only; never invent ieee_id/coden from acronym alone."""
    result = JournalResolutionResult()
    candidates: list[tuple[int, EvidenceKind, IeeeJournalMeta]] = []

    if evidence.issn:
        by_issn = lookup_ieee_journal(issn=evidence.issn)
        if by_issn:
            candidates.append((1, "pdf_issn", by_issn))
            result.evidence.append(("pdf_issn", evidence.issn))

    if evidence.doi:
        by_doi = lookup_ieee_journal(doi=evidence.doi)
        if by_doi:
            candidates.append((2, "pdf_doi", by_doi))
            result.evidence.append(("pdf_doi", evidence.doi))

    if evidence.journal_title:
        by_title = lookup_ieee_journal(journal_title=evidence.journal_title)
        if by_title:
            candidates.append((3, "pdf_title", by_title))
            result.evidence.append(("pdf_title", evidence.journal_title))
        else:
            result.journal_title = evidence.journal_title

    if evidence.ir_journal_header:
        by_ir = lookup_ieee_journal(journal_title=evidence.ir_journal_header)
        if by_ir:
            candidates.append((4, "ir_journal_header", by_ir))
            result.evidence.append(("ir_journal_header", evidence.ir_journal_header))

    prefix = _filename_prefix_candidate(evidence.source_filename)
    if prefix:
        by_prefix = _match_by_filename_prefix(prefix)
        if by_prefix:
            candidates.append((5, "filename_prefix", by_prefix))
            result.evidence.append(("filename_prefix", prefix))

    if not candidates:
        if evidence.journal_title and not result.journal_title:
            result.journal_title = evidence.journal_title
        if not result.journal and not result.journal_title:
            result.warnings.append("journal_unresolved: no verified registry match")
        return result

    candidates.sort(key=lambda item: item[0])
    chosen_kind, chosen = candidates[0][1], candidates[0][2]
    for priority, kind, record in candidates[1:]:
        if record.acronym != chosen.acronym:
            result.warnings.append(
                f"journal_evidence_conflict: kept {chosen.acronym} from {chosen_kind}, "
                f"ignored {record.acronym} from {kind} (priority {priority})"
            )

    result.journal = chosen
    result.journal_title = chosen.title
    logger.info(
        "Resolved journal %s via %s (evidence=%s)",
        chosen.acronym,
        chosen_kind,
        result.evidence,
    )
    return result


@dataclass(frozen=True)
class TemplateJournalSnapshot:
    ieee_id: str | None = None
    acronym: str | None = None
    coden: str | None = None
    title: str | None = None


def read_template_journal_meta(article: Any) -> TemplateJournalSnapshot:
    from lxml import etree

    if not isinstance(article, etree._Element):
        return TemplateJournalSnapshot()
    front = article.find("front")
    if front is None:
        return TemplateJournalSnapshot()
    journal_meta = front.find("journal-meta")
    if journal_meta is None:
        return TemplateJournalSnapshot()

    def _jid(id_type: str) -> str | None:
        for node in journal_meta.findall("journal-id"):
            if node.get("journal-id-type") == id_type:
                text = (node.text or "").strip()
                return text or None
        return None

    title_el = journal_meta.find(".//journal-title")
    title = (title_el.text or "").strip() if title_el is not None else None
    return TemplateJournalSnapshot(
        ieee_id=_jid("ieee"),
        acronym=_jid("acronym"),
        coden=_jid("coden"),
        title=title,
    )


def validate_against_template(
    resolution: JournalResolutionResult,
    template: TemplateJournalSnapshot,
) -> JournalResolutionResult:
    if resolution.journal is None:
        if template.acronym or template.ieee_id:
            resolution.warnings.append(
                "template_journal_not_applied: source journal unverified; "
                "template identifiers will not be copied"
            )
        return resolution

    if template.acronym and template.acronym.upper() != resolution.journal.acronym.upper():
        resolution.template_mismatch = True
        resolution.warnings.append(
            f"template_journal_mismatch: template={template.acronym} "
            f"source={resolution.journal.acronym}"
        )
        logger.warning(
            "Sample template journal %s differs from source PDF journal %s; using source.",
            template.acronym,
            resolution.journal.acronym,
        )
    return resolution


def clear_unverified_journal_identifiers(journal_meta: Any) -> None:
    """Remove template journal ids when source journal could not be verified."""
    from lxml import etree

    if not isinstance(journal_meta, etree._Element):
        return
    for node in list(journal_meta.findall("journal-id")):
        journal_meta.remove(node)
    for node in list(journal_meta.findall("issn")):
        journal_meta.remove(node)
