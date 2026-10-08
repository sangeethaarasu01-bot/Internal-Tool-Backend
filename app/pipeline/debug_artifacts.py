"""Write inspectable debug bundles for pipeline stages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.models.extracted_document import ExtractedDocument
from app.models.extraction import ExtractionResult


def write_phase1_debug_bundle(
    output_dir: Path,
    *,
    pdf_path: Path,
    phase1: ExtractedDocument,
    full_extraction: ExtractionResult | None = None,
    copy_pdf: bool = True,
) -> dict[str, str]:
    """
    Persist Phase 1 artifacts for debugging failed PDFs.

    Returns a map of artifact role → file path (strings).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    if copy_pdf and pdf_path.is_file():
        dest = output_dir / "original.pdf"
        if pdf_path.resolve() != dest.resolve():
            shutil.copy2(pdf_path, dest)
        paths["original_pdf"] = str(dest)

    phase1_path = output_dir / "phase1_document.json"
    phase1_path.write_text(phase1.model_dump_json(indent=2), encoding="utf-8")
    paths["phase1_document"] = str(phase1_path)

    raw_extracted_path = output_dir / "raw_extracted_text.txt"
    raw_extracted_path.write_text(phase1.raw_text or "", encoding="utf-8")
    paths["raw_extracted_text"] = str(raw_extracted_path)

    normalized_path = output_dir / "normalized_extracted_text.txt"
    normalized_path.write_text(phase1.normalized_text or "", encoding="utf-8")
    paths["normalized_extracted_text"] = str(normalized_path)

    # Backward-compatible alias (unsanitized PyMuPDF reading-order text).
    raw_text_path = output_dir / "extracted_raw_text.txt"
    raw_text_path.write_text(phase1.raw_text or "", encoding="utf-8")
    paths["extracted_raw_text"] = str(raw_text_path)

    report = phase1.extraction_quality.invalid_character_report
    if report is not None:
        invalid_path = output_dir / "invalid_character_report.json"
        invalid_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        paths["invalid_character_report"] = str(invalid_path)

    quality_path = output_dir / "extraction_quality.json"
    quality_path.write_text(
        phase1.extraction_quality.model_dump_json(indent=2),
        encoding="utf-8",
    )
    paths["extraction_quality"] = str(quality_path)

    if full_extraction is not None:
        layout_path = output_dir / "layout_extraction.json"
        layout_payload = full_extraction.model_dump()
        layout_payload["figures"] = [fig.model_dump() for fig in phase1.figures]
        layout_payload["tables"] = [table.model_dump() for table in phase1.tables]
        layout_path.write_text(json.dumps(layout_payload, indent=2), encoding="utf-8")
        paths["layout_extraction"] = str(layout_path)

    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    if figures_dir.is_dir():
        paths["figures_dir"] = str(figures_dir)
    if tables_dir.is_dir():
        paths["tables_dir"] = str(tables_dir)

    manifest = {
        "schema_version": "1.0.0",
        "stage": "phase1_pdf_extraction",
        "artifacts": paths,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    paths["manifest"] = str(manifest_path)
    return paths
