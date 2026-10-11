"""Amara TCE proof PDF: author-query cover must not become title/authors."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extraction_workflow import apply_scope_to_extraction
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.template_parser import TemplateParser
from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
AMARA_TEMPLATE = ROOT / "data" / "outputs" / "tce-amarakorba-3658363-proof.pdf1.xml"
AMARA_TITLE_FRAGMENT = "Split Multi-Task Federated Learning"
AMARA_AUTHOR_FRAGMENT = "Amara Korba"

_CANDIDATE_PDFS = [
    ROOT / "data" / "pipeline_debug" / "tce-amarakorba-3658363-proof.pdf1.pdf" / "original.pdf",
    ROOT / "uploads" / "tce-amarakorba-3658363-proof.pdf1.pdf",
    ROOT.parent.parent / "tce-amarakorba-3658363-proof.pdf1.pdf",
]


def _find_amara_pdf() -> Path | None:
    for path in _CANDIDATE_PDFS:
        if path.is_file():
            return path
    return None


@pytest.mark.slow
def test_amara_proof_pdf_front_matter_not_author_queries() -> None:
    pdf = _find_amara_pdf()
    if pdf is None:
        pytest.skip("Amara proof PDF fixture not on disk")
    if not AMARA_TEMPLATE.is_file():
        pytest.skip("Amara template fixture missing")

    raw = extract_text_layout(str(pdf))
    full = build_full_extraction_result(raw, include_tagged_output=False)
    schema = TemplateParser(AMARA_TEMPLATE).parse().model_dump(mode="json")
    scoped = apply_scope_to_extraction(scope="full", result=full.model_dump(), template_schema=schema)
    ir = scoped["filtered_ir"]
    front = ir.get("front") or {}

    title_el = front.get("title") or {}
    title = title_el.get("text") or ""
    for item in title_el.get("elements") or []:
        title += str(item.get("value") or "")

    assert AMARA_TITLE_FRAGMENT in title
    assert "AUTHOR QUERIES" not in title.upper()

    authors: list[str] = []
    for author in front.get("authors") or []:
        text = author.get("text") or ""
        for item in author.get("elements") or []:
            text += str(item.get("value") or "")
        if text.strip():
            authors.append(text.strip())

    assert 1 <= len(authors) <= 12
    assert any(AMARA_AUTHOR_FRAGMENT in name for name in authors)
    assert not any("AQ:" in name or "please answer" in name.lower() for name in authors)
