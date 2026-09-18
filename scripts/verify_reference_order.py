"""Verify bibliography extraction order for a PDF."""

from __future__ import annotations

import logging
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.text_extractor import extract_text_layout
from app.services.ir_semantic_adapter import fill_back_references_from_ir, ir_to_semantic_mapping
from app.services.extraction_workflow import ir_from_extraction_result
from app.services.layout.document_pipeline import build_full_extraction_result, process_document_structure
from app.services.xml_generator import generate_jats_xml
from app.utils.reference_assembler import (
    AssembledReference,
    ReferenceParsingError,
    parse_reference_number,
    validate_reference_sequence,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


def main(pdf_path: str) -> int:
    raw = extract_text_layout(pdf_path)
    structure = process_document_structure(raw)
    sem = structure.semantic
    if sem is None:
        print("No semantic document produced")
        return 1

    refs = sem.back.references
    numbers = [parse_reference_number(ref.label) for ref in refs]
    page_numbers = [
        ref.page_numbers[0]
        for ref in refs
        if ref.page_numbers
    ]

    print("=== EXTRACTION RESULTS ===")
    print("Reference section start page:", min(page_numbers) if page_numbers else None)
    print("Reference section end page:", max(page_numbers) if page_numbers else None)
    print("Total references detected:", len(refs))
    print("First 20 reference numbers:", numbers[:20])
    print("Last 20 reference numbers:", numbers[-20:])

    counts = Counter(numbers)
    duplicates = sorted(number for number, count in counts.items() if count > 1)
    missing = [number for number in range(1, max(numbers) + 1) if number not in counts]
    print("Duplicate reference numbers:", duplicates)
    print("Missing reference numbers:", missing)

    assembled = [
        AssembledReference(
            parse_reference_number(ref.label) or 0,
            ref.label or "",
            ref.text or "",
            list(ref.source_block_ids),
            list(ref.page_numbers or []),
            ref.bbox,
            ref.confidence or 1.0,
        )
        for ref in refs
        if parse_reference_number(ref.label) is not None
    ]
    try:
        validate_reference_sequence(assembled)
        print("Reference order validation: PASS")
    except ReferenceParsingError as exc:
        print("Reference order validation: FAIL")
        print(str(exc))
        return 1

    full = build_full_extraction_result(raw)
    ir = ir_from_extraction_result(full.model_dump(mode="json"))
    mapping = fill_back_references_from_ir(ir_to_semantic_mapping(ir), ir)
    template = ROOT / "tests" / "fixtures" / "minimal_template.xml"
    if not template.exists():
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text(
            '<?xml version="1.0"?>'
            "<article><front/><body/><back>"
            "<ref-list><title>References</title></ref-list>"
            "</back></article>",
            encoding="utf-8",
        )
    xml = generate_jats_xml(str(template), mapping)
    document = etree.fromstring(xml.encode("utf-8"))
    xml_refs = document.findall(".//ref-list/ref")
    print("XML <ref> count:", len(xml_refs))
    return 0


if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else str(
        ROOT / "uploads" / "extractions" / "20260918_132226_access-khan-3639184-proof1.pdf"
    )
    raise SystemExit(main(pdf))
