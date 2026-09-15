"""Stage 1 structure/completeness validation report. Not part of product API."""

from __future__ import annotations

from pathlib import Path

from app.services.layout.document_pipeline import process_document_structure
from app.services.text_extractor import extract_text_layout

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


def find_ieee_proof_pdf() -> Path:
    candidates = sorted(
        UPLOADS_DIR.glob("*jsen-banerjeeroy*proof1.pdf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    any_pdf = sorted(UPLOADS_DIR.glob("*proof1.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if any_pdf:
        return any_pdf[0]
    raise FileNotFoundError(f"No proof PDF in {UPLOADS_DIR}")


def preview(text: str, n: int = 80) -> str:
    return (text or "").replace("\n", " ")[:n]


def main() -> None:
    pdf = find_ieee_proof_pdf()
    raw = extract_text_layout(str(pdf.resolve()))
    structure = process_document_structure(raw)

    print("STRUCTURE VALIDATION")
    print(f"PDF filename: {pdf.name}")
    print(f"Page count: {raw.document.page_count}")
    print()
    print("### Extraction")
    print(f"Total blocks: {raw.stats.total_blocks}")
    print(f"Total lines: {raw.stats.total_lines}")
    print(f"Total spans: {sum(len(ln.spans) for pg in raw.pages for b in pg.blocks for ln in b.lines)}")
    print(f"Total raw characters: {raw.stats.total_chars}")
    print()
    print("### Filtering")
    print(f"Removed footer blocks: {structure.structure_stats.footers}")
    print(f"Removed running headers: {structure.structure_stats.running_headers}")
    print(f"Removed page numbers: {structure.structure_stats.page_numbers}")
    print(f"Removed characters: {structure.completeness.excluded_char_count}")
    print("Reasons for exclusion:")
    for key, value in structure.completeness.exclusion_summary.items():
        print(f"  {key}: {value} chars")
    print()
    print("### Structure")
    print(f"Detected sections: {structure.structure_stats.detected_sections}")
    print(f"Detected paragraphs: {structure.structure_stats.detected_paragraphs}")
    print(f"Detected references: {structure.structure_stats.detected_references}")
    print(f"Unknown blocks: {structure.structure_stats.unknown_blocks}")
    print()
    print("### Completeness")
    print(f"Raw text characters: {structure.completeness.raw_char_count}")
    print(f"Retained text characters: {structure.completeness.retained_char_count}")
    print(f"Excluded text characters: {structure.completeness.excluded_char_count}")
    print(f"Unclassified text characters: {structure.completeness.unclassified_char_count}")
    print()
    print("### Per-page block classification")
    for page in raw.pages:
        print(f"\nPAGE {page.page_number}")
        page_blocks = [b for b in structure.blocks if b.page_number == page.page_number]
        page_blocks.sort(key=lambda b: b.reading_order_index)
        for block in page_blocks:
            print(
                f"{block.block_id}\n"
                f"{block.classification}\n"
                f"{block.column}\n"
                f"{block.bbox}\n"
                f"{preview(block.text)!r}\n"
            )

    checks = {
        "p7_b19_not_footer": any(
            b.block_id == "p7_b19"
            and b.classification == "REFERENCE_TEXT"
            and not b.exclude_from_content
            for b in structure.blocks
        ),
        "p2_b0_running_header": any(
            b.block_id == "p2_b0" and b.classification == "RUNNING_HEADER"
            for b in structure.blocks
        ),
        "footer_excluded": structure.structure_stats.footers >= 1,
        "no_silent_loss": (
            structure.completeness.retained_char_count
            + structure.completeness.excluded_char_count
            >= structure.completeness.raw_char_count * 0.95
        ),
    }
    print("\n### Spot checks")
    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    overall = all(checks.values())
    print(f"\nOVERALL: {'STRUCTURE VALIDATION PASS' if overall else 'FAIL'}")


if __name__ == "__main__":
    main()
