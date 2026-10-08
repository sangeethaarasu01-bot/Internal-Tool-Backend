#!/usr/bin/env python3
"""CLI: generic table extraction from academic PDFs.

Tiered engines per page: Camelot (lattice/stream) → img2table → PyMuPDF → pdfplumber,
with PyMuPDF ingest + RapidFuzz caption matching in the shared pipeline package.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as script from repo: backend/scripts/extract_tables.py
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.pipeline.phase1.figure_export import default_figures_dir
from app.pipeline.table_extraction import print_validation_report, run_extraction, write_output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract tables from an academic PDF into structured JSON.",
    )
    parser.add_argument("input_pdf", type=Path, help="Path to input PDF")
    parser.add_argument("output_json", type=Path, help="Path to output JSON file")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save page PNGs and table bbox overlays next to the output JSON",
    )
    parser.add_argument("--verbose", action="store_true", help="Detailed per-step logs")
    parser.add_argument(
        "--dump-regions",
        action="store_true",
        help="Write per-table caption region JSON dumps",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=None,
        help="Directory for extracted figure PNGs (default: <output_json_dir>/figures/)",
    )
    args = parser.parse_args()

    if not args.input_pdf.is_file():
        print(f"Input PDF not found: {args.input_pdf}", file=sys.stderr)
        return 1

    debug_dir = args.output_json.parent / f"{args.output_json.stem}_debug" if args.debug else None
    regions_dir = (
        args.output_json.parent / f"{args.output_json.stem}_regions"
        if args.dump_regions
        else None
    )

    figures_dir = args.figures_dir or default_figures_dir(args.output_json)

    data = run_extraction(
        args.input_pdf,
        debug=args.debug,
        verbose=args.verbose,
        debug_dir=debug_dir,
        dump_regions=args.dump_regions,
        dump_regions_dir=regions_dir,
        figures_dir=figures_dir,
        output_json=args.output_json,
    )
    write_output(data, args.output_json)
    print_validation_report(data)
    print(f"Wrote {data['table_count']} table(s) to {args.output_json}")
    print(f"Wrote {data.get('figure_count', 0)} figure(s) to {figures_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
