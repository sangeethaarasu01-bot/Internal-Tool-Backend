#!/usr/bin/env python3
"""Run Phase 1 PDF extraction locally and write a debug bundle (no LLM, no MongoDB)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline.debug_artifacts import write_phase1_debug_bundle
from app.pipeline.phase1.extract import Phase1ExtractionError, extract_pdf_document


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 PDF → intermediate representation")
    parser.add_argument("pdf", type=Path, help="Path to input PDF")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Debug output directory (default: data/pipeline_debug/<pdf-stem>)",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    out_dir = args.output_dir or (ROOT / "data" / "pipeline_debug" / pdf_path.stem)

    try:
        phase1, full = extract_pdf_document(pdf_path, bundle_dir=out_dir)
    except Phase1ExtractionError as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1

    paths = write_phase1_debug_bundle(
        out_dir,
        pdf_path=pdf_path,
        phase1=phase1,
        full_extraction=full,
    )
    print(f"document_type={phase1.document_type}")
    print(f"pages={len(phase1.pages)} chars={phase1.extraction_quality.extracted_character_count}")
    print(f"Debug bundle: {out_dir}")
    for role, path in paths.items():
        print(f"  {role}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
