#!/usr/bin/env python3
"""
Clear a job's template binding and regenerate DocBook metadata template from Phase 1.

Use before retrying POST /generate-xml when a 409 identity mismatch proves the wrong
publisher XML was bound (e.g. Marshall template on a Pastoral PDF job).

Example:
  python scripts/rebind_template_from_source.py 6ac8ed8914c9adeeda8a1464
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routes.extractions import create_template_from_source  # noqa: E402
from app.services.source_identity import (  # noqa: E402
    build_source_identity_from_extraction_doc,
    build_template_identity,
)
from app.database import extractions_col  # noqa: E402
from bson import ObjectId  # noqa: E402


def _oid(extraction_id: str) -> ObjectId:
    return ObjectId(extraction_id)


async def rebind(extraction_id: str) -> dict:
    doc = extractions_col().find_one({"_id": _oid(extraction_id)})
    if not doc:
        raise SystemExit(f"Extraction not found: {extraction_id}")

    old = doc.get("template") or {}
    old_identity = (old.get("template_identity") or {}).get("title") or old.get("original_filename")

    response = await create_template_from_source(extraction_id)

    doc = extractions_col().find_one({"_id": _oid(extraction_id)}) or {}
    template = doc.get("template") or {}
    path = template.get("file_path")
    source = build_source_identity_from_extraction_doc({**doc, "_id": extraction_id})
    template_id_obj = build_template_identity(template, path) if path else None

    xml_snippet = ""
    if path and Path(path).is_file():
        text = Path(path).read_text(encoding="utf-8")
        xml_snippet = text[:500]
        if "6520177" in text or "9798216520177" in text:
            print("WARNING: regenerated template still contains Marshall book_id/DOI fragment", file=sys.stderr)

    return {
        "extraction_id": extraction_id,
        "cleared_previous": old_identity,
        "new_template_id": response.template_id,
        "new_filename": response.original_filename,
        "source_title": source.title,
        "source_isbn": source.isbn,
        "source_year": source.publication_year,
        "template_title": template_id_obj.title if template_id_obj else None,
        "template_isbn": template_id_obj.isbn if template_id_obj else None,
        "xml_preview": xml_snippet,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extraction_id", help="Mongo extraction job id")
    args = parser.parse_args()
    summary = asyncio.run(rebind(args.extraction_id))
    print(json.dumps(summary, indent=2, default=str))
    if summary.get("template_title") and summary.get("source_title"):
        if "Student Apathy" in (summary["template_title"] or "") and "Pastoral" in (
            summary["source_title"] or ""
        ):
            raise SystemExit("Template title still mismatches source — do not retry generate-xml.")


if __name__ == "__main__":
    main()
