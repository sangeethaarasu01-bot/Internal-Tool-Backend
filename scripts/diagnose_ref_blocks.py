"""Diagnose bibliography block structure in a PDF."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.layout.document_pipeline import process_document_structure
from app.services.layout.semantic_patterns import split_reference_entries
from app.services.layout.semantic_signals import _is_author_bio
from app.services.text_extractor import extract_text_layout
from app.utils.reference_assembler import collect_reference_section_blocks

LABEL_RE = re.compile(r"\[(\d+)\]")


def main(pdf_path: str) -> None:
    raw = extract_text_layout(pdf_path)
    structure = process_document_structure(raw)
    section_blocks = collect_reference_section_blocks(
        structure.blocks,
        {},
        is_author_bio=_is_author_bio,
    )
    print("section blocks", len(section_blocks))

    all_labels: list[int] = []
    for block in section_blocks:
        labels = [int(match.group(1)) for match in LABEL_RE.finditer(block.text or "")]
        all_labels.extend(labels)
        height = block.bbox[3] - block.bbox[1]
        suffix = "..." if len(labels) > 8 else ""
        print(
            f"page={block.page_number} col={block.column} "
            f"y0={block.bbox[1]:.1f} h={height:.1f} "
            f"labels={labels[:8]}{suffix} count={len(labels)}"
        )
        splits = split_reference_entries(block.text or "")
        if splits:
            first = splits[0][0]
            last = splits[-1][0]
            print(f"  split_entries={len(splits)} first={first} last={last}")

    print("total label matches", len(all_labels))
    print("unique labels", len(set(all_labels)), "min", min(all_labels), "max", max(all_labels))


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else str(
        ROOT / "uploads" / "extractions" / "20260918_132226_access-khan-3639184-proof1.pdf"
    )
    main(pdf)
