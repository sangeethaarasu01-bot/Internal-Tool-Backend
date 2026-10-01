"""Build PaperData from the layout-aware Stage-1 extraction pipeline."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import settings
from app.models.extraction import ExtractionResult
from app.models.ir_schema import IRNode
from app.models.paper import Affiliation, Author, PaperData, Reference, Section
from app.models.semantic_document import SemanticDocument, SemanticSection
from app.services.layout.document_pipeline import process_document_structure
from app.services.layout.semantic_patterns import parse_author_names, split_section_label_and_title
from app.services.text_extractor import extract_text_layout
from app.utils.logger import logger


def _ir_text(node: IRNode | None) -> str:
    if node is None:
        return ""
    return (node.text or "").strip()


def _semantic_section_to_paper(sec: SemanticSection, sec_index: int) -> Section:
    label, title = split_section_label_and_title(sec.heading or "")
    if not title:
        title = (sec.heading or "").strip() or f"Section {sec_index}"
    paragraphs: list[str] = []
    for node in sec.paragraphs:
        text = _ir_text(node)
        if text:
            paragraphs.append(text)
    for node in sec.content:
        if node.type in ("paragraph", "BODY_TEXT", "PARAGRAPH"):
            text = _ir_text(node)
            if text:
                paragraphs.append(text)
    subsections = [
        _semantic_section_to_paper(sub, sec_index * 10 + i + 1)
        for i, sub in enumerate(sec.subsections)
    ]
    return Section(
        id=f"sec{sec_index}",
        label=label or None,
        title=title,
        level=sec.level or 1,
        paragraphs=paragraphs,
        subsections=subsections,
    )


def _authors_from_front(semantic: SemanticDocument) -> list[Author]:
    authors: list[Author] = []
    for node in semantic.front.authors:
        raw = _ir_text(node)
        if not raw:
            continue
        for name in parse_author_names(raw):
            name = name.strip()
            if not name or len(name) < 4:
                continue
            parts = name.split()
            authors.append(
                Author(
                    first_name=parts[0] if parts else "",
                    last_name=parts[-1] if len(parts) > 1 else "",
                    full_name=name,
                )
            )
    return authors[:20]


def _affiliations_from_front(semantic: SemanticDocument) -> list[Affiliation]:
    affs: list[Affiliation] = []
    for idx, node in enumerate(semantic.front.affiliations[:12], start=1):
        text = _ir_text(node)
        if not text:
            continue
        affs.append(Affiliation(id=f"aff{idx}", institution=text))
    return affs


def _keywords_from_front(semantic: SemanticDocument) -> list[str]:
    node = semantic.front.keywords
    if node is None:
        return []
    if node.keywords:
        return [k.strip() for k in node.keywords if k.strip()]
    raw = _ir_text(node)
    if not raw:
        return []
    raw = re.sub(r"^(index terms|keywords)\s*[—\-–:]?\s*", "", raw, flags=re.I)
    return [k.strip() for k in re.split(r"[;,]", raw) if k.strip()]


def _references_from_back(semantic: SemanticDocument) -> list[Reference]:
    refs: list[Reference] = []
    for idx, node in enumerate(semantic.back.references, start=1):
        raw = _ir_text(node)
        if not raw:
            continue
        num = idx
        label_m = re.match(r"^\[(\d+)\]", raw)
        if label_m:
            num = int(label_m.group(1))
        refs.append(Reference(id=f"ref{num}", number=num, raw_text=raw))
    return refs


def _trim_extraction_result(raw: ExtractionResult) -> ExtractionResult:
    max_pages = settings.MAX_PDF_PAGES
    if max_pages and len(raw.pages) > max_pages:
        pages = raw.pages[:max_pages]
        char_counts = [p.text_char_count for p in pages]
        stats = raw.stats.model_copy(
            update={
                "total_blocks": sum(len(p.blocks) for p in pages),
                "total_lines": sum(
                    len(b.lines) for p in pages for b in p.blocks
                ),
                "total_chars": sum(char_counts),
            }
        )
        doc = raw.document.model_copy(update={"page_count": len(pages)})
        return ExtractionResult(document=doc, pages=pages, stats=stats)
    return raw


def semantic_document_to_paper(semantic: SemanticDocument) -> PaperData:
    title = _ir_text(semantic.front.title)
    abstract = _ir_text(semantic.front.abstract)
    authors = _authors_from_front(semantic)
    affiliations = _affiliations_from_front(semantic)
    keywords = _keywords_from_front(semantic)
    sections = [
        _semantic_section_to_paper(sec, i + 1) for i, sec in enumerate(semantic.body.sections)
    ]
    if not sections and semantic.body.loose_paragraphs:
        paras = [_ir_text(p) for p in semantic.body.loose_paragraphs]
        paras = [p for p in paras if p]
        if paras:
            sections = [
                Section(
                    id="sec1",
                    title="Body",
                    level=1,
                    paragraphs=paras,
                )
            ]
    references = _references_from_back(semantic)
    warnings: list[str] = []
    if not title:
        warnings.append("Layout pipeline: title not detected")
    if not sections:
        warnings.append("Layout pipeline: no body sections detected")
    return PaperData(
        title=title,
        authors=authors,
        affiliations=affiliations,
        abstract=abstract,
        keywords=keywords,
        sections=sections,
        references=references,
        metadata={"extraction_engine": "layout_pipeline_v2"},
        extraction_warnings=warnings,
    )


def extract_paper_via_layout(pdf_path: Path) -> PaperData:
    """High-quality PDF → PaperData using reading order + semantic classification."""
    raw = extract_text_layout(str(pdf_path), pdf_path.name)
    raw = _trim_extraction_result(raw)
    structure = process_document_structure(raw)
    semantic = structure.semantic
    if semantic is None:
        raise RuntimeError("Layout pipeline produced no semantic document")
    paper = semantic_document_to_paper(semantic)
    logger.info(
        "Layout PDF extract: title={} authors={} sections={} paras={}",
        (paper.title or "")[:80],
        len(paper.authors),
        len(paper.sections),
        sum(len(s.paragraphs) for s in paper.sections),
    )
    return paper
