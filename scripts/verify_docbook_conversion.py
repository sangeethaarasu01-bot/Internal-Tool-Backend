#!/usr/bin/env python3
"""Verify DocBook conversion: PDF IR + sample template -> output checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lxml import etree

from app.services.extraction_workflow import ir_from_extraction_result
from app.services.identity_gates import verify_post_generation_identity
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.output_format import OUTPUT_DOCBOOK_5
from app.services.source_identity import build_source_identity_from_extraction_doc
from app.services.template_format import DOCBOOK_NS
from app.utils.xml_helpers import xml_local_name
from app.services.xml_output_router import generate_output_xml

DEFAULT_LAYOUT = ROOT / "data" / "pipeline_debug" / "6acae32dbff2db96245fc3e5" / "layout_extraction.json"
DEFAULT_TEMPLATE = Path(
    r"c:\Users\ponar\Downloads\9798216520177_txt_xml\9798216520177_txt_xml\9798216520177_txt_xml.xml"
)
OUT_PATH = ROOT / "data" / "outputs" / "verify_pastoral_docbook.xml"


def main() -> int:
    layout_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LAYOUT
    template_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TEMPLATE

    if not layout_path.is_file():
        print(f"MISSING layout: {layout_path}")
        return 1
    if not template_path.is_file():
        print(f"MISSING template: {template_path}")
        return 1

    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    phase1 = layout.get("document") or {}
    if not phase1.get("title"):
        phase1_path = layout_path.parent / "phase1_document.json"
        if phase1_path.is_file():
            phase1 = json.loads(phase1_path.read_text(encoding="utf-8"))

    doc = {
        "_id": layout_path.parent.name,
        "original_filename": phase1.get("source_filename") or "9798216211563_web.pdf",
        "source_pdf_sha256": "verify-local",
        "page_count": phase1.get("page_count") or len(phase1.get("pages") or []),
        "phase1": phase1,
    }
    source = build_source_identity_from_extraction_doc(doc)
    ir = ir_from_extraction_result(layout)
    mapping = ir_to_semantic_mapping(ir)

    schema = {"template_format": "docbook_5_book", "root_tag": "book"}
    xml, fmt, result = generate_output_xml(
        template_path,
        schema,
        mapping,
        output_format=OUTPUT_DOCBOOK_5,
        source=source,
        ir=ir,
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(xml, encoding="utf-8")

    root = etree.fromstring(xml.encode("utf-8"))
    chapters = root.findall(f".//{{{DOCBOOK_NS}}}chapter")
    paras = root.findall(f".//{{{DOCBOOK_NS}}}para")
    def _under_info(el: etree._Element) -> bool:
        for anc in el.iterancestors():
            if xml_local_name(anc) == "info":
                return True
        return False

    body_paras = [el for el in paras if not _under_info(el)]
    text_blob = " ".join("".join(el.itertext()) for el in body_paras).lower()
    full_text = xml.lower()

    checks = {
        "format_docbook": fmt == OUTPUT_DOCBOOK_5,
        "body_merge_applied": bool(result and result.body.applied),
        "metadata_overlay": bool(result and result.metadata.applied),
        "has_chapters": len(chapters) >= 1,
        "para_count": len(paras),
        "title_pastoral": "pastoral bearings" in full_text,
        "pdf_phrase_lived_religion": "lived religion" in text_blob,
        "no_marshall_apathy_in_chapters": "overcoming student apathy" not in text_blob,
        "no_marshall_author_bio_in_chapters": "jeff marshall began his career" not in text_blob,
        "no_marshall_apathy_in_info": "overcoming student apathy" not in full_text,
        "no_rowman_template_url": "rowman.com" not in full_text,
        "no_marshall_copyright_holder": "jeff c. marshall" not in full_text,
        "no_revhistory": "<revhistory" not in full_text,
        "no_workflow_biblioids": "schematronversion" not in full_text.replace("-", ""),
        "copyright_holder_lexington": "lexington books" in full_text,
        "pastoral_isbn_in_info": "9780739123607" in full_text.replace("-", ""),
        "no_marshall_isbn_text": "9788216520177" not in full_text.replace("-", "")
        and "147580660" not in full_text.replace("-", ""),
    }

    try:
        verify_post_generation_identity(
            extraction_id=doc["_id"],
            source=source,
            xml_content=xml,
            output_format=OUTPUT_DOCBOOK_5,
            expected_root="book",
        )
        checks["identity_gate"] = True
    except Exception as exc:
        checks["identity_gate"] = False
        print(f"identity_gate_failed: {exc}")

    print("=== DocBook conversion verification ===")
    print(f"layout:   {layout_path}")
    print(f"template: {template_path}")
    print(f"output:   {OUT_PATH}")
    print(f"IR body top-level nodes: {len(mapping.body)}")
    print(f"chapters: {len(chapters)}  paras: {len(paras)}")
    print(f"xml_bytes: {len(xml.encode('utf-8')):,}")
    print()
    failed = [k for k, v in checks.items() if k != "para_count" and not v]
    for key, ok in checks.items():
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {key}" + (f" = {checks[key]}" if key == "para_count" else ""))

    if failed:
        print("\nRESULT: FAILED", ", ".join(failed))
        return 2
    print("\nRESULT: PASSED — PDF body in DocBook <book>, Marshall template narrative removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
