"""Move misplaced front matter out of body.loose_paragraphs (idempotent)."""

from __future__ import annotations

import re
from typing import Any

from app.models.semantic_document import SemanticBody, SemanticDocument, SemanticFrontMatter
from app.pipeline.phase1.ir_text import ir_node_plain_text
from app.services.layout.semantic_patterns import (
    ABSTRACT_RE,
    KEYWORDS_RE,
    REFERENCE_HEADING_RE,
    is_roman_section_heading,
    normalize_text,
)
from app.utils.front_matter_recovery import (
    append_abstract_segment_to_front,
    is_keywords_continuation,
    is_post_keywords_abstract_fragment,
    is_running_header_noise,
    parse_index_terms_keywords,
    recover_article_title,
    strip_abstract_label,
)
from app.utils.proof_pdf import is_plausible_author_name

_SECTION_START_RE = re.compile(r"^(?:\d+\.|[IVX]+\.)\s+[A-Z]", re.I)


def _node_plain(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    if node.get("text"):
        return normalize_text(str(node["text"]))
    parts: list[str] = []
    for element in node.get("elements") or []:
        if element.get("value"):
            parts.append(str(element["value"]))
    if parts:
        return normalize_text("".join(parts))
    for child in node.get("children") or []:
        child_text = _node_plain(child)
        if child_text:
            parts.append(child_text)
    return normalize_text(" ".join(parts))


def _merge_keywords_segment(front: SemanticFrontMatter, segment: str) -> None:
    from app.services.layout.semantic_builder import _element

    segment = normalize_text(segment)
    if not segment:
        return
    existing = ir_node_plain_text(front.keywords) if front.keywords else ""
    combined = f"{existing} {segment}".strip() if existing else segment
    keywords = parse_index_terms_keywords(combined)
    front.keywords = _element(
        "KEYWORDS",
        combined,
        [],
        0.86,
        keywords=keywords,
    )


def _title_matches(text: str, title: str) -> bool:
    left = re.sub(r"\s+", " ", text.strip().lower())
    right = re.sub(r"\s+", " ", title.strip().lower())
    return left == right or (len(right) > 30 and right in left)


def _classify_loose_paragraph(
    text: str,
    front: SemanticFrontMatter,
    *,
    keywords_closed: bool,
) -> str:
    """Return ``drop``, ``title``, ``abstract``, ``keywords``, or ``keep``."""
    if not text.strip():
        return "drop"
    if is_running_header_noise(text):
        return "drop"
    if (
        is_plausible_author_name(text)
        and len(text.split()) <= 8
        and not is_keywords_continuation(text)
    ):
        return "drop"
    title_text = ir_node_plain_text(front.title) if front.title else ""
    if title_text and _title_matches(text, title_text):
        return "drop"
    if ABSTRACT_RE.match(text):
        return "abstract"
    if front.abstract and is_post_keywords_abstract_fragment(text):
        return "abstract"
    if KEYWORDS_RE.match(text) or (front.keywords and is_keywords_continuation(text)):
        return "keywords"
    if front.abstract and not keywords_closed and not KEYWORDS_RE.match(text):
        if (
            not is_roman_section_heading(text)
            and not _SECTION_START_RE.match(text)
            and not REFERENCE_HEADING_RE.match(text)
            and len(text) > 20
            and not is_running_header_noise(text)
            and not KEYWORDS_RE.search(text)
        ):
            return "abstract"
    if not front.title and len(text) >= 35 and not ABSTRACT_RE.match(text) and not KEYWORDS_RE.match(text):
        if (
            "IEEE TRANSACTIONS" not in text.upper()
            and not is_plausible_author_name(text)
            and not front.abstract
            and not is_keywords_continuation(text)
        ):
            return "title"
    return "keep"


def consolidate_semantic_front_matter(document: SemanticDocument) -> None:
    """Relocate front matter trapped in ``body.loose_paragraphs`` (idempotent)."""
    front = document.front
    body = document.body
    if not body.loose_paragraphs:
        return

    keywords_closed = front.keywords is not None
    kept: list[Any] = []
    for paragraph in body.loose_paragraphs:
        text = ir_node_plain_text(paragraph)
        action = _classify_loose_paragraph(text, front, keywords_closed=keywords_closed)
        if action == "drop":
            continue
        if action == "title":
            from app.services.layout.semantic_builder import _element

            if not front.title:
                front.title = _element("TITLE", text, [], 0.84)
            continue
        if action == "abstract":
            append_abstract_segment_to_front(front, text)
            continue
        if action == "keywords":
            _merge_keywords_segment(front, text)
            keywords_closed = True
            continue
        kept.append(paragraph)

    body.loose_paragraphs = kept


def repair_ir_front_matter(
    ir: dict[str, Any],
    *,
    processed_blocks: list[Any] | None = None,
) -> dict[str, Any]:
    """Idempotent IR repair before semantic mapping."""
    from app.utils.front_matter_recovery import (
        coerce_processed_blocks,
        recover_abstract_tail_from_unmapped_blocks,
    )

    body = ir.get("body") or {}
    loose = list(body.get("loose_paragraphs") or [])

    front_dict = dict(ir.get("front") or {})
    keywords_closed = bool(front_dict.get("keywords"))

    class _FrontProxy:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data
            self.title = _dict_to_ir_node(data.get("title"))
            self.abstract = _dict_to_ir_node(data.get("abstract"))
            self.keywords = _dict_to_ir_node(data.get("keywords"))

        def sync_back(self) -> None:
            if self.title:
                self._data["title"] = self.title.to_json_dict()
            if self.abstract:
                self._data["abstract"] = self.abstract.to_json_dict()
            if self.keywords:
                self._data["keywords"] = self.keywords.to_json_dict()

    def _dict_to_ir_node(raw: dict[str, Any] | None):
        if not raw:
            return None
        from app.models.ir_schema import IRNode

        return IRNode.model_validate(raw)

    proxy = _FrontProxy(front_dict)
    kept: list[dict[str, Any]] = []

    for node in loose:
        text = _node_plain(node)
        action = _classify_loose_paragraph(text, proxy, keywords_closed=keywords_closed)
        if action == "drop":
            continue
        if action == "title" and not proxy.title:
            from app.services.layout.semantic_builder import _element

            proxy.title = _element("TITLE", text, [], 0.84)
            continue
        if action == "abstract":
            append_abstract_segment_to_front(proxy, text)
            continue
        if action == "keywords":
            _merge_keywords_segment(proxy, text)
            keywords_closed = True
            continue
        kept.append(node)

    processed = coerce_processed_blocks(processed_blocks)
    if processed and proxy.abstract:
        recover_abstract_tail_from_unmapped_blocks(proxy, processed, set())

    proxy.sync_back()
    ir["front"] = front_dict
    body["loose_paragraphs"] = kept
    ir["body"] = body
    return ir


def recover_title_if_missing(
    document: SemanticDocument,
    processed: list,
    title_threshold: float,
    *,
    can_merge_title,
) -> None:
    if document.front.title:
        return
    recovered = recover_article_title(
        processed,
        title_threshold,
        can_merge_title=can_merge_title,
    )
    if not recovered:
        return
    from app.services.layout.semantic_builder import _element

    candidate, blocks, confidence = recovered
    document.front.title = _element("TITLE", candidate, blocks, confidence)
