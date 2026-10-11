"""Phase 1 bibliography must be stable and survive layout section collection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.document_structure import DocumentStructureResult, ProcessedBlock
from app.pipeline.phase1.build_document import _build_references
from app.services.layout.semantic_signals import _is_author_bio
from app.utils.reference_assembler import (
    assemble_references_from_blocks,
    collect_reference_section_blocks,
    parse_reference_number,
)

ROOT = Path(__file__).resolve().parent.parent
KAKICHI_LAYOUT = ROOT / "data" / "pipeline_debug" / "6acaab7f5f507de506bce2d8" / "layout_extraction.json"
KAKICHI_LAYOUT_B = ROOT / "data" / "pipeline_debug" / "6acab21330b94a16dffdd479" / "layout_extraction.json"
KHAN_LAYOUT = ROOT / "data" / "pipeline_debug" / "6acaf5f36f6fcd9cdedbf80d" / "layout_extraction.json"


def _structure_from_layout(path: Path) -> DocumentStructureResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    structure = payload.get("structure") or payload
    return DocumentStructureResult.model_validate(structure)


@pytest.mark.skipif(not KAKICHI_LAYOUT.is_file(), reason="Kakichi layout fixture missing")
def test_collect_reference_blocks_starts_after_references_heading() -> None:
    structure = _structure_from_layout(KAKICHI_LAYOUT)
    sem_types = {block.block_id: block.classification for block in structure.blocks}
    blocks = collect_reference_section_blocks(
        structure.blocks,
        sem_types,
        is_author_bio=_is_author_bio,
    )
    block_ids = {block.block_id for block in blocks}
    assert "p15_b17" not in block_ids
    assert "p15_b2" not in block_ids
    assert "p15_b18" in block_ids


@pytest.mark.skipif(not KHAN_LAYOUT.is_file(), reason="Khan IEEE Access layout fixture missing")
def test_khan_two_column_reference_page_includes_refs_before_heading() -> None:
    structure = _structure_from_layout(KHAN_LAYOUT)
    sem_types = {block.block_id: block.classification for block in structure.blocks}
    blocks = collect_reference_section_blocks(
        structure.blocks,
        sem_types,
        is_author_bio=_is_author_bio,
    )
    block_ids = {block.block_id for block in blocks}
    assert "p23_b9" in block_ids
    assert "p23_b2" not in block_ids
    refs = assemble_references_from_blocks(blocks, validate=True)
    numbers = [parse_reference_number(ref.label) for ref in refs]
    assert numbers[0] == 1
    assert numbers == list(range(1, len(numbers) + 1))
    assert len(numbers) >= 100


@pytest.mark.skipif(not KAKICHI_LAYOUT.is_file(), reason="Kakichi layout fixture missing")
def test_build_references_stable_for_same_layout() -> None:
    structure = _structure_from_layout(KAKICHI_LAYOUT)
    first = _build_references(structure)
    second = _build_references(structure)
    assert len(first) >= 28
    assert len(first) == len(second)
    assert [item.text for item in first] == [item.text for item in second]


@pytest.mark.skipif(
    not KAKICHI_LAYOUT.is_file() or not KAKICHI_LAYOUT_B.is_file(),
    reason="Kakichi layout fixtures missing",
)
def test_build_references_equivalent_for_two_jobs_same_pdf_layout() -> None:
    structure_a = _structure_from_layout(KAKICHI_LAYOUT)
    structure_b = _structure_from_layout(KAKICHI_LAYOUT_B)
    refs_a = _build_references(structure_a)
    refs_b = _build_references(structure_b)
    assert len(refs_a) == len(refs_b)
    assert len(refs_a) >= 28
