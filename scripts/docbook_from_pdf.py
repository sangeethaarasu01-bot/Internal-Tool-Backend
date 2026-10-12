#!/usr/bin/env python3
"""
PDF + DocBook 5.0 book template -> generated book XML (no MongoDB).

Usage:
  python scripts/docbook_from_pdf.py --pdf path/to/book.pdf --template path/to/template.xml
  python scripts/docbook_from_pdf.py --pdf book.pdf --template template.xml --out book_out.xml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline.phase1.build_document import build_extracted_document
from app.pipeline.phase1.extraction_build_options import ExtractionBuildOptions
from app.services.extraction_workflow import ir_from_extraction_result
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.layout.document_pipeline import build_full_extraction_result
from app.services.output_format import OUTPUT_DOCBOOK_5
from app.services.source_identity import build_source_identity_from_extraction_doc
from app.services.template_parser import TemplateParser
from app.services.text_extractor import extract_text_layout
from app.services.xml_output_router import generate_output_xml


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_extraction(pdf_path: Path, *, skip_tables_figures: bool) -> dict:
    raw = extract_text_layout(str(pdf_path), original_filename=pdf_path.name)
    full = build_full_extraction_result(raw, include_tagged_output=False)
    options = ExtractionBuildOptions(skip_tables_figures=skip_tables_figures)
    phase1 = build_extracted_document(
        raw,
        structure=full.structure,
        pdf_path=pdf_path,
        bundle_dir=None,
        options=options,
    )
    result_payload = full.model_dump()
    result_payload["phase1"] = phase1.model_dump()
    return {
        "result": result_payload,
        "phase1": phase1.model_dump(),
        "page_count": raw.document.page_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate DocBook 5.0 XML from PDF + template.")
    parser.add_argument("--pdf", type=Path, required=True, help="Source PDF")
    parser.add_argument("--template", type=Path, required=True, help="DocBook 5.0 <book> template XML")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output XML path (default: data/outputs/<pdf_stem>_docbook.xml)",
    )
    parser.add_argument(
        "--skip-tables-figures",
        action="store_true",
        help="Faster extraction; skip table/figure pipeline",
    )
    parser.add_argument(
        "--write-debug",
        type=Path,
        default=None,
        help="Optional directory to write extraction result JSON for debugging",
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    template_path = args.template.resolve()
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    if not template_path.is_file():
        print(f"Template not found: {template_path}", file=sys.stderr)
        return 1

    out_path = args.out or (ROOT / "data" / "outputs" / f"{pdf_path.stem}_docbook.xml")
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Extracting: {pdf_path.name} ({pdf_path.stat().st_size // 1024} KiB)")
    bundle = run_extraction(pdf_path, skip_tables_figures=args.skip_tables_figures)
    result = bundle["result"]
    phase1 = bundle["phase1"]

    if args.write_debug:
        debug_dir = args.write_debug.resolve()
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "extraction_result.json").write_text(
            json.dumps(result, ensure_ascii=False)[:50_000_000],
            encoding="utf-8",
        )

    ir = ir_from_extraction_result(result)
    mapping = ir_to_semantic_mapping(ir)
    body_nodes = len(mapping.body or [])
    print(f"IR body sections: {body_nodes}")

    schema = TemplateParser(template_path).parse().model_dump(mode="json")
    if schema.get("template_format") != "docbook_5_book":
        print(
            f"Template root is not DocBook 5.0 <book> (got {schema.get('template_format')}).",
            file=sys.stderr,
        )
        return 1

    doc = {
        "_id": "local-cli",
        "original_filename": pdf_path.name,
        "source_pdf_sha256": _sha256_file(pdf_path),
        "page_count": bundle["page_count"],
        "phase1": phase1,
        "result": result,
    }
    source = build_source_identity_from_extraction_doc(doc)

    print(f"Generating DocBook from template: {template_path.name}")
    xml, fmt, gen_result = generate_output_xml(
        template_path,
        schema,
        mapping,
        output_format=OUTPUT_DOCBOOK_5,
        source=source,
        ir=ir,
    )
    out_path.write_text(xml, encoding="utf-8")
    print(f"Wrote {fmt} -> {out_path} ({len(xml) // 1024} KiB)")
    if gen_result and gen_result.body.warnings:
        for warning in gen_result.body.warnings[:12]:
            print(f"  warn: {warning}")
        if len(gen_result.body.warnings) > 12:
            print(f"  ... and {len(gen_result.body.warnings) - 12} more warnings")
    if gen_result and gen_result.metadata.warnings:
        for warning in gen_result.metadata.warnings[:8]:
            print(f"  meta: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
