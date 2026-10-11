"""Trace abstract fragments through generate-xml stages for one extraction job."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from pymongo import MongoClient

from app.pipeline.phase1.ir_text import ir_node_plain_text
from app.services.front_matter_consolidation import repair_ir_front_matter, _node_plain
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.extraction_workflow import apply_scope_to_extraction
from app.utils.front_matter_recovery import coerce_processed_blocks, recover_abstract_tail_from_unmapped_blocks

MARKERS = ("1.80%", "significantly outperforming", "in real-world EV systems")


def _has_markers(text: str) -> dict[str, bool]:
    t = (text or "").lower()
    return {
        "1.80%": "1.80%" in text,
        "significantly outperforming": "significantly outperforming" in t,
        "in real-world EV systems": "in real-world ev systems" in t,
        "approximately state-of-the-art (bad)": "approximately state-of-the-art" in t,
    }


def _find_job(col):
    for doc in col.find({"status": "completed"}).sort("_id", -1).limit(50):
        blob = json.dumps(doc.get("result") or {}, default=str)
        if "SMTFL" in blob or "Split Multi-Task Federated" in blob:
            return doc
    q = col.find_one(
        {"result.structure.blocks.text": {"$regex": "1\\.80%", "$options": "i"}},
    )
    return q


def main() -> None:
    uri = os.environ.get("MONGODB_URI")
    db_name = os.environ.get("MONGODB_DB", "ieee_converter")
    if not uri:
        print("MONGODB_URI not set")
        sys.exit(1)
    col = MongoClient(uri)[db_name]["extractions"]
    doc = _find_job(col)
    if not doc:
        print("No matching extraction found")
        sys.exit(2)
    eid = str(doc["_id"])
    print(f"extraction_id={eid}")
    structure = (doc.get("result") or {}).get("structure") or {}
    blocks = structure.get("blocks") or []
    processed = coerce_processed_blocks(blocks)
    print(f"blocks_count={len(blocks)}")

    from app.services.layout.semantic_patterns import KEYWORDS_RE
    from app.utils.front_matter_recovery import (
        is_post_keywords_abstract_fragment,
        _ordered_content_blocks,
    )

    keywords_seen = False
    for b in _ordered_content_blocks(processed):
        if b.page_number > 1:
            break
        tx = (b.text or "").strip()
        if KEYWORDS_RE.match(tx):
            keywords_seen = True
            print(f"  KEYWORDS ro={b.reading_order_index} {b.block_id}: {tx[:80]!r}")
        if keywords_seen and is_post_keywords_abstract_fragment(tx):
            print(
                f"  TAIL_CANDIDATE ro={b.reading_order_index} {b.block_id}: {tx[:80]!r}"
            )
        if any(m in tx for m in ("1.80%", "real-world EV", "approximately", "state-of-the-art")):
            print(
                f"  block {b.block_id} ro={b.reading_order_index} col={b.column}: {tx[:100]!r}"
            )

    template_schema = (doc.get("template") or {}).get("template_schema") or {}
    scope_result = apply_scope_to_extraction(
        scope="full",
        result=doc["result"],
        template_schema=template_schema,
    )
    ir = scope_result["filtered_ir"]
    front = ir.get("front") or {}
    abs_before = _node_plain(front.get("abstract"))
    print("\nSTAGE ir.abstract (before repair):", _has_markers(abs_before))
    print(f"  tail: ...{abs_before[-120:]!r}" if abs_before else "  (empty)")

    ir2 = json.loads(json.dumps(ir))
    repair_ir_front_matter(ir2, processed_blocks=blocks)
    abs_repair = _node_plain((ir2.get("front") or {}).get("abstract"))
    print("\nSTAGE after repair_ir_front_matter:", _has_markers(abs_repair))
    print(f"  tail: ...{abs_repair[-160:]!r}" if abs_repair else "  (empty)")

    mapping = ir_to_semantic_mapping(json.loads(json.dumps(scope_result["filtered_ir"])), processed_blocks=blocks)
    abs_map = (mapping.front or {}).get("abstract")
    if isinstance(abs_map, dict):
        from app.services.ir_semantic_adapter import _node_text

        abs_map_text = _node_text(abs_map) or ""
    else:
        abs_map_text = str(abs_map)
    print("\nSTAGE mapping.front.abstract:", _has_markers(abs_map_text))
    print(f"  tail: ...{abs_map_text[-160:]!r}" if abs_map_text else "  (empty)")

    semantic = (doc.get("result") or {}).get("structure", {}).get("semantic") or {}
    if semantic:
        try:
            from app.models.semantic_document import SemanticDocument

            sem = SemanticDocument.model_validate(semantic)
            sem_abs = ir_node_plain_text(sem.front.abstract) if sem.front.abstract else ""
            print("\nSTAGE stored semantic.front.abstract:", _has_markers(sem_abs))
            print(f"  tail: ...{sem_abs[-160:]!r}" if sem_abs else "  (empty)")
        except Exception as exc:
            print(f"\nSTAGE stored semantic: parse error {exc}")


if __name__ == "__main__":
    main()
