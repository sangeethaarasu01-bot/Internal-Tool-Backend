#!/usr/bin/env python3
"""Run Stage 1 extraction locally and print tables/figures/text stats (no Mongo)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.pipeline.phase1.build_document import build_extracted_document
from app.pipeline.phase1.extraction_build_options import ExtractionBuildOptions
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.text_extractor import extract_text_layout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to PDF file")
    parser.add_argument(
        "--skip-tables-figures",
        action="store_true",
        help="Same as UI checkbox: skip Step 4 assets",
    )
    args = parser.parse_args()
    pdf = args.pdf.resolve()
    if not pdf.is_file():
        raise SystemExit(f"PDF not found: {pdf}")

    raw = extract_text_layout(str(pdf), original_filename=pdf.name)
    full = build_full_extraction_result(raw, include_tagged_output=False)
    pages = raw.document.page_count
    fast = pages >= settings.EXTRACTION_LARGE_PDF_PAGE_THRESHOLD
    opts = ExtractionBuildOptions(
        skip_tables_figures=args.skip_tables_figures,
        fast_tables_figures=fast,
    )
    doc = build_extracted_document(
        raw,
        structure=full.structure,
        pdf_path=pdf,
        options=opts,
    )
    d = doc.model_dump()
    print(f"pages={pages} large_pdf_fast_mode={fast} skip_tables_figures={args.skip_tables_figures}")
    print(f"chars={d.get('extracted_character_count')} blocks={raw.stats.total_blocks}")
    print(f"tables={len(d.get('tables') or [])} figures={len(d.get('figures') or [])}")
    print(f"step4_partial={opts.partial_step4}")
    if args.skip_tables_figures:
        print("NOTE: skip_tables_figures=True — tables/figures intentionally empty.")


if __name__ == "__main__":
    main()
