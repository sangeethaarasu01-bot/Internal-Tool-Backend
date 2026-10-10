"""Overlay PDF / Phase 1 metadata onto IEEE JATS article templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from app.constants.ieee_journals import IeeeJournalMeta, lookup_ieee_journal
from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.source_identity import SourceIdentityRecord
from app.utils.xml_text import set_lxml_text

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;)]+", re.I)
DATE_HISTORY_RE = re.compile(
    r"(received|revised|accepted)\s+(\d{1,2}\s+\w+\.?\s+\d{4}|\w+\.?\s+\d{1,2},?\s+\d{4})",
    re.I,
)
VOLUME_LINE_RE = re.compile(r"VOLUME\s+(\d+)\s*,\s*(\d{4})", re.I)
ARTICLE_NUM_RE = re.compile(r"(\d{7})")
IEEE_ACCESS_RE = re.compile(r"\bIEEE\s+Access\b", re.I)
NUMBERED_AFF_RE = re.compile(r"(?<!\d)(\d)(?=[A-Za-z])")
NUMBERED_EQUATION_RE = re.compile(r"(?<![\d.])\((\d{1,3})\)(?![\d])")

XLINK_NS = "http://www.w3.org/1999/xlink"


@dataclass
class JatsMetadataOverlayResult:
    journal: IeeeJournalMeta | None = None
    journal_title: str | None = None
    doi: str | None = None
    manuscript_id: str | None = None
    publication_year: int | None = None
    fig_count: int | None = None
    table_count: int | None = None
    equation_count: int | None = None
    ref_count: int | None = None
    page_count: int | None = None
    applied_fields: list[str] = field(default_factory=list)


def _header_text(phase1: dict[str, Any] | None) -> str:
    if not phase1:
        return ""
    for key in ("normalized_text", "raw_text"):
        text = phase1.get(key)
        if isinstance(text, str) and text.strip():
            return text
    pages = phase1.get("pages") or []
    if pages and isinstance(pages[0], dict):
        return str(pages[0].get("raw_page_text") or "")
    return ""


def _parse_history(header: str) -> dict[str, str]:
    history: dict[str, str] = {}
    for kind, value in DATE_HISTORY_RE.findall(header[:4000]):
        key = kind.lower()
        if key == "revised" and "revised" in history:
            key = "reviseddate1"
        history[key] = value.strip()
    return history


def _parse_doi(header: str) -> str | None:
    abstract_pos = header.upper().find("ABSTRACT")
    search_region = header[:abstract_pos] if abstract_pos > 0 else header[:8000]
    for match in DOI_RE.finditer(search_region):
        candidate = match.group(0).rstrip(".;,)")
        if "ACCESS" in candidate.upper() or "TCE" in candidate.upper() or "TIA" in candidate.upper():
            return candidate
    match = DOI_RE.search(search_region)
    return match.group(0).rstrip(".;,)") if match else None


def _infer_article_number(source_filename: str | None, phase1: dict[str, Any] | None) -> str | None:
    for value in (
        source_filename,
        (phase1 or {}).get("source_filename"),
    ):
        if not value:
            continue
        match = ARTICLE_NUM_RE.search(str(value))
        if match:
            return match.group(1)
    return None


def _infer_manuscript_id(
    header: str,
    source_filename: str | None,
    article_number: str | None,
) -> str | None:
    ms = re.search(r"\b([A-Z]{2,10}-\d{4}-\d{2}-\d{3,6})\b", header[:6000])
    if ms:
        return ms.group(1)
    if IEEE_ACCESS_RE.search(header) or (source_filename and "access-" in source_filename.lower()):
        year = None
        vol = VOLUME_LINE_RE.search(header)
        if vol:
            year = vol.group(2)
        if article_number and year:
            return f"ACCESS-{year}-{article_number}"
    return None


def _infer_doi(
    header: str,
    publication_year: int | None,
    article_number: str | None,
    source_filename: str | None,
) -> str | None:
    parsed = _parse_doi(header)
    if parsed:
        return parsed
    year = publication_year or 2026
    if not article_number:
        return None
    if IEEE_ACCESS_RE.search(header) or (source_filename and "access-" in source_filename.lower()):
        return f"10.1109/ACCESS.{year}.{article_number}"
    return None


def _detect_journal_title(
    header: str,
    ir: dict[str, Any] | None,
    source_filename: str | None = None,
) -> str | None:
    front = (ir or {}).get("front") or {}
    journal = front.get("journal_header")
    if isinstance(journal, dict):
        text = journal.get("text") or ""
        for item in journal.get("elements") or []:
            text += str(item.get("value") or "")
        text = text.strip()
        if text and "consumer electronics" not in text.lower():
            return text
    if IEEE_ACCESS_RE.search(header):
        return "IEEE Access"
    if VOLUME_LINE_RE.search(header) and source_filename and "access-" in source_filename.lower():
        return "IEEE Access"
    return None


def _count_numbered_equations(text: str) -> int | None:
    numbers = [int(value) for value in NUMBERED_EQUATION_RE.findall(text)]
    if not numbers:
        return None
    return max(numbers)


def _phase1_stats(phase1: dict[str, Any] | None) -> dict[str, Any]:
    if not phase1:
        return {}
    for key in ("extraction_quality", "stats", "extraction_stats"):
        stats = phase1.get(key)
        if isinstance(stats, dict) and stats:
            return stats
    return {}


def _count_mapping_nodes(
    mapping: SemanticMappingBody,
    semantic_type: str,
) -> int:
    total = 0

    def walk(nodes: list[Any]) -> None:
        nonlocal total
        for node in nodes:
            if isinstance(node, dict):
                st = str(node.get("semantic_type") or "")
                children = node.get("children") or []
            else:
                st = node.semantic_type
                children = node.children
            if st == semantic_type:
                total += 1
            if children:
                walk(list(children))

    walk(list(mapping.body))
    return total


def _count_references(mapping: SemanticMappingBody, ir: dict[str, Any] | None = None) -> int:
    mapping_refs = (mapping.back or {}).get("references") or []
    ir_refs = ((ir or {}).get("back") or {}).get("references") or []
    refs = ir_refs if len(ir_refs) >= len(mapping_refs) else mapping_refs
    return len(refs)


def build_jats_metadata_overlay(
    *,
    phase1: dict[str, Any] | None,
    ir: dict[str, Any] | None,
    mapping: SemanticMappingBody,
    source: SourceIdentityRecord | None = None,
) -> JatsMetadataOverlayResult:
    header = _header_text(phase1)
    stats = _phase1_stats(phase1)
    volume = VOLUME_LINE_RE.search(header)
    publication_year = source.publication_year if source else None
    if publication_year is None and volume:
        try:
            publication_year = int(volume.group(2))
        except (TypeError, ValueError):
            publication_year = None

    article_number = _infer_article_number(
        source.source_filename if source else None,
        phase1,
    )
    journal_title = _detect_journal_title(
        header,
        ir,
        source.source_filename if source else None,
    )
    doi = _infer_doi(header, publication_year, article_number, source.source_filename if source else None)
    manuscript_id = _infer_manuscript_id(
        header,
        source.source_filename if source else None,
        article_number,
    )

    fig_count = stats.get("figure_count") or stats.get("figures_extracted")
    if fig_count is None:
        fig_count = _count_mapping_nodes(mapping, "figure")
    table_count = stats.get("detected_table_count") or stats.get("tables_extracted")
    if table_count is None:
        table_count = _count_mapping_nodes(mapping, "table")
    equation_count = _count_numbered_equations(header)
    if equation_count is None:
        equation_count = stats.get("equation_count")
    if equation_count is None:
        equation_count = _count_mapping_nodes(mapping, "display_math")
    ref_count = _count_references(mapping, ir)
    page_count = None
    if phase1 and phase1.get("pages"):
        page_count = len(phase1["pages"])
    elif source and source.page_count:
        page_count = source.page_count

    journal = lookup_ieee_journal(
        journal_title=journal_title,
        doi=doi,
        source_filename=source.source_filename if source else None,
    )
    if journal and not journal_title:
        journal_title = journal.title

    return JatsMetadataOverlayResult(
        journal=journal,
        journal_title=journal_title,
        doi=doi,
        manuscript_id=manuscript_id,
        publication_year=publication_year,
        fig_count=int(fig_count) if fig_count is not None else None,
        table_count=int(table_count) if table_count is not None else None,
        equation_count=int(equation_count) if equation_count is not None else None,
        ref_count=ref_count or None,
        page_count=int(page_count) if page_count is not None else None,
    )


def infer_figure_graphic_prefix(source_filename: str | None) -> tuple[str, str] | None:
    """Return ``(name_prefix, article_number)`` for IEEE-style ``{prefix}{n}-{num}.eps``."""
    if not source_filename:
        return None
    lowered = source_filename.lower()
    article_number = _infer_article_number(source_filename, None)
    prefix_match = re.search(r"access-([a-z]+)-", lowered)
    if prefix_match:
        return prefix_match.group(1), article_number or "1"
    stem = re.sub(r"\.(pdf|xml).*$", "", lowered, flags=re.I)
    stem = re.sub(r"[-_]?proof$", "", stem)
    parts = re.split(r"[-_]", stem)
    prefix = parts[-2] if len(parts) >= 2 and parts[-1].isdigit() else parts[0]
    if not prefix or prefix == "access":
        prefix = "fig"
    return prefix, article_number or "1"


def build_source_figure_graphics(
    *,
    source_filename: str | None,
    phase1: dict[str, Any] | None,
) -> dict[str, str]:
    """Map ``figN`` ids to source PDF graphic basenames (not template sample files)."""
    inferred = infer_figure_graphic_prefix(source_filename)
    graphics: dict[str, str] = {}
    figures = (phase1 or {}).get("figures") or []
    for item in figures:
        if not isinstance(item, dict):
            continue
        fig_num = item.get("figure_number")
        if fig_num is None:
            fig_id = str(item.get("figure_id") or item.get("id") or "")
            digits = re.sub(r"\D+", "", fig_id)
            fig_num = int(digits) if digits else None
        if fig_num is None:
            continue
        fig_key = f"fig{fig_num}"
        if inferred:
            prefix, article_number = inferred
            graphics[fig_key] = f"{prefix}{fig_num}-{article_number}.eps"
        else:
            graphics[fig_key] = f"{fig_key}.eps"
    if not graphics and inferred:
        prefix, article_number = inferred
        for index in range(1, 41):
            graphics[f"fig{index}"] = f"{prefix}{index}-{article_number}.eps"
    return graphics


def _split_numbered_affiliations(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    parts = NUMBERED_AFF_RE.sub(r"\n\1", normalized).splitlines()
    entries: list[str] = []
    for part in parts:
        cleaned = re.sub(r"^\d+", "", part.strip()).strip()
        if cleaned:
            entries.append(cleaned)
    return entries or [normalized]


def _set_article_id(article_meta: etree._Element, pub_type: str, value: str) -> None:
    for node in article_meta.findall("article-id"):
        if node.get("pub-id-type") == pub_type:
            set_lxml_text(node, value, log_context={"semantic_type": "metadata", "source": "-", "field": pub_type})
            return
    node = etree.SubElement(article_meta, "article-id", {"pub-id-type": pub_type})
    set_lxml_text(node, value, log_context={"semantic_type": "metadata", "source": "-", "field": pub_type})


def _apply_history(article_meta: etree._Element, history: dict[str, str]) -> None:
    if not history:
        return
    hist = article_meta.find("history")
    if hist is None:
        hist = etree.SubElement(article_meta, "history")
    else:
        for child in list(hist):
            hist.remove(child)
    mapping = {
        "received": "receiveddate",
        "revised": "reviseddate1",
        "reviseddate1": "reviseddate1",
        "accepted": "accepteddate",
    }
    for key, value in history.items():
        dtype = mapping.get(key, key)
        date_el = etree.SubElement(hist, "date", {"date-type": dtype})
        set_lxml_text(
            etree.SubElement(date_el, "string-date"),
            value,
            log_context={"semantic_type": "metadata", "source": "-", "field": dtype},
        )


def _apply_affiliations(article_meta: etree._Element, mapping: SemanticMappingBody) -> None:
    aff_nodes = (mapping.front or {}).get("affiliations") or []
    if not aff_nodes:
        return
    texts: list[str] = []
    for node in aff_nodes:
        if isinstance(node, dict):
            text = node.get("text") or ""
            for item in node.get("elements") or []:
                text += str(item.get("value") or "")
        else:
            text = node.text or ""
            for item in node.elements:
                text += item.value or ""
        text = text.strip()
        if text:
            texts.extend(_split_numbered_affiliations(text))
    if not texts:
        return
    for aff in list(article_meta.findall("aff")):
        article_meta.remove(aff)
    for index, institution in enumerate(texts, start=1):
        aff = etree.SubElement(article_meta, "aff", id=f"aff{index}")
        wrap = etree.SubElement(aff, "institution-wrap")
        inst = etree.SubElement(wrap, "institution", {"content-type": "institution"})
        set_lxml_text(
            inst,
            institution,
            log_context={"semantic_type": "affiliation", "source": "-", "field": "institution"},
        )


def _apply_counts(article_meta: etree._Element, overlay: JatsMetadataOverlayResult) -> None:
    counts = article_meta.find("counts")
    if counts is None:
        counts = etree.SubElement(article_meta, "counts")
    specs = (
        ("fig-count", overlay.fig_count),
        ("table-count", overlay.table_count),
        ("equation-count", overlay.equation_count),
        ("page-count", overlay.page_count),
    )
    for tag, value in specs:
        if value is None:
            continue
        node = counts.find(tag)
        if node is None:
            node = etree.SubElement(counts, tag)
        node.set("count", str(value))


def _set_journal_id(journal_meta: etree._Element, id_type: str, value: str) -> None:
    for node in journal_meta.findall("journal-id"):
        if node.get("journal-id-type") == id_type:
            set_lxml_text(
                node,
                value,
                log_context={"semantic_type": "metadata", "source": "-", "field": f"journal-id-{id_type}"},
            )
            return
    node = etree.SubElement(journal_meta, "journal-id", {"journal-id-type": id_type})
    set_lxml_text(
        node,
        value,
        log_context={"semantic_type": "metadata", "source": "-", "field": f"journal-id-{id_type}"},
    )


def _set_issn(journal_meta: etree._Element, publication_format: str, value: str) -> None:
    for node in journal_meta.findall("issn"):
        if node.get("publication-format") == publication_format:
            set_lxml_text(
                node,
                value,
                log_context={"semantic_type": "metadata", "source": "-", "field": f"issn-{publication_format}"},
            )
            return
    node = etree.SubElement(journal_meta, "issn", {"publication-format": publication_format})
    set_lxml_text(
        node,
        value,
        log_context={"semantic_type": "metadata", "source": "-", "field": f"issn-{publication_format}"},
    )


def _apply_journal_meta(article: etree._Element, journal: IeeeJournalMeta | None) -> None:
    if journal is None:
        return
    front = article.find("front")
    if front is None:
        return
    journal_meta = front.find("journal-meta")
    if journal_meta is None:
        journal_meta = etree.SubElement(front, "journal-meta")

    _set_journal_id(journal_meta, "ieee", journal.ieee_id)
    _set_journal_id(journal_meta, "acronym", journal.acronym)
    _set_journal_id(journal_meta, "coden", journal.coden)

    title_group = journal_meta.find("journal-title-group")
    if title_group is None:
        title_group = etree.SubElement(journal_meta, "journal-title-group")
    journal_title_el = title_group.find("journal-title")
    if journal_title_el is None:
        journal_title_el = etree.SubElement(title_group, "journal-title")
    set_lxml_text(
        journal_title_el,
        journal.title,
        log_context={"semantic_type": "metadata", "source": "-", "field": "journal-title"},
    )

    _set_issn(journal_meta, "print", journal.issn_print)
    _set_issn(journal_meta, "online", journal.issn_online)

    publisher = journal_meta.find("publisher")
    if publisher is None:
        publisher = etree.SubElement(journal_meta, "publisher")
    publisher_name = publisher.find("publisher-name")
    if publisher_name is None:
        publisher_name = etree.SubElement(publisher, "publisher-name")
    if not (publisher_name.text or "").strip():
        set_lxml_text(
            publisher_name,
            "IEEE",
            log_context={"semantic_type": "metadata", "source": "-", "field": "publisher-name"},
        )


def _clear_template_funding(article_meta: etree._Element) -> None:
    for group in list(article_meta.findall("funding-group")):
        article_meta.remove(group)


def apply_jats_metadata_overlay(
    article: etree._Element,
    *,
    overlay: JatsMetadataOverlayResult,
    mapping: SemanticMappingBody,
    phase1: dict[str, Any] | None = None,
) -> JatsMetadataOverlayResult:
    """Apply source metadata; returns the same overlay with ``applied_fields`` populated."""
    applied: list[str] = []
    front = article.find("front")
    article_meta = front.find("article-meta") if front is not None else None
    if article_meta is None:
        return overlay

    header = _header_text(phase1)
    history = _parse_history(header)

    if overlay.journal:
        _apply_journal_meta(article, overlay.journal)
        applied.append("journal-meta")
    elif overlay.journal_title:
        _apply_journal_meta(
            article,
            lookup_ieee_journal(journal_title=overlay.journal_title, doi=overlay.doi),
        )
        applied.append("journal-title")

    if overlay.doi:
        _set_article_id(article_meta, "doi", overlay.doi)
        applied.append("doi")
    if overlay.manuscript_id:
        _set_article_id(article_meta, "manuscript", overlay.manuscript_id)
        applied.append("manuscript")

    if overlay.publication_year:
        pub_date = article_meta.find("pub-date")
        if pub_date is None:
            pub_date = etree.SubElement(
                article_meta,
                "pub-date",
                {
                    "date-type": "cover",
                    "iso-8601-date": str(overlay.publication_year),
                    "pub-type": "print",
                    "publication-format": "pdf",
                },
            )
        year_el = pub_date.find("year")
        if year_el is None:
            year_el = etree.SubElement(pub_date, "year")
        set_lxml_text(
            year_el,
            str(overlay.publication_year),
            log_context={"semantic_type": "metadata", "source": "-", "field": "pub-year"},
        )
        applied.append("pub-date")

    if history:
        _apply_history(article_meta, history)
        applied.append("history")

    _apply_affiliations(article_meta, mapping)
    if (mapping.front or {}).get("affiliations"):
        applied.append("affiliations")

    _clear_template_funding(article_meta)
    applied.append("funding-cleared")

    _apply_counts(article_meta, overlay)
    applied.append("counts")

    overlay.applied_fields = applied
    return overlay
