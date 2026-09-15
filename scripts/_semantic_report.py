"""Semantic classification report for IEEE validation PDF."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.services.layout.document_pipeline import process_document_structure
from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
PDF = next(iter(sorted(UPLOADS.glob("*20260907_132003*proof1.pdf"), reverse=True)), UPLOADS / "20260907_132003_jsen-banerjeerroy-3639180-proof1.pdf")


def _walk_sections(sections, counts: Counter) -> None:
    for sec in sections:
        counts[sec.heading_element.type] += 1
        for item in sec.content:
            counts[item.type] += 1
        for para in sec.paragraphs:
            if para not in sec.content:
                counts[para.type] += 1
        _walk_sections(sec.subsections, counts)


def _collect_lists(sections, lists: list) -> None:
    for sec in sections:
        for item in sec.content:
            if item.type == "LIST":
                lists.append(item)
        _collect_lists(sec.subsections, lists)


def _count_nested_lists(element) -> int:
    nested = 0
    for child in element.children:
        if child.type == "LIST":
            nested += 1
            nested += _count_nested_lists(child)
        nested += _count_nested_lists(child)
    return nested


def main() -> None:
    if not PDF.exists():
        print(f"PDF not found: {PDF}")
        return

    raw = extract_text_layout(str(PDF))
    structure = process_document_structure(raw)
    sem = structure.semantic
    assert sem is not None

    counts: Counter = Counter()
    _walk_sections(sem.body.sections, counts)
    for p in sem.body.loose_paragraphs:
        counts[p.type] += 1
    for ref in sem.back.references:
        counts[ref.type] += 1
    for u in sem.unknown:
        counts[u.type] += 1

    if sem.front.title:
        counts["TITLE"] += 1
    if sem.front.abstract:
        counts["ABSTRACT"] += 1
    if sem.front.keywords:
        counts["KEYWORDS"] += 1

    lists: list = []
    _collect_lists(sem.body.sections, lists)
    for item in sem.body.loose_paragraphs:
        if item.type == "LIST":
            lists.append(item)

    bullet_lists = [lst for lst in lists if lst.list_type == "bullet"]
    ordered_lists = [lst for lst in lists if lst.list_type == "order"]
    list_items = sum(len(lst.children) for lst in lists)
    nested_lists = sum(_count_nested_lists(lst) for lst in lists)

    print("=== IEEE Semantic Report ===")
    print(f"Raw blocks: {len(structure.blocks)}")
    print(f"Raw chars: {sem.completeness.raw_character_count}")
    print(f"Structured chars: {sem.completeness.structured_character_count}")
    print(f"Excluded chars: {sem.completeness.excluded_character_count}")
    print(f"Unknown elements: {sem.completeness.unknown_element_count}")
    print(f"Unmapped blocks: {len(sem.completeness.unmapped_block_ids)}")
    print("\nList detection summary:")
    print(f"  total lists: {len(lists)}")
    print(f"  bullet lists: {len(bullet_lists)}")
    print(f"  ordered lists: {len(ordered_lists)}")
    print(f"  total list items: {list_items}")
    print(f"  nested lists: {nested_lists}")
    print(f"  unknown text count: {sem.completeness.unknown_element_count}")

    for idx, lst in enumerate(lists, start=1):
        print(f"\nLIST #{idx}")
        print(f"  type: {lst.list_type}")
        print(f"  page: {','.join(str(p) for p in lst.page_numbers)}")
        print(f"  items: {len(lst.children)}")
        for item_idx, item in enumerate(lst.children, start=1):
            print(f"\n  ITEM {item_idx}")
            print(f"    marker: {item.list_marker}")
            preview = item.text[:80] + ("..." if len(item.text) > 80 else "")
            print(f"    text: {preview}")

    print("\nSemantic elements by type:")
    for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {k}: {v}")

    print("\n=== Sample validations ===")
    tagged = sem.tagged_output
    checks = [
        ("III. RESULTS", "III. RESULTS AND DISCUSSIONS" in tagged),
        ("B. Clustering SUBSECTION", "B. Clustering Using t-SNE" in tagged),
        ("F. Response SUBSECTION", "F. Response Recording From e-Tongue" in tagged),
        ("LIST_ITEM", "list-item" in tagged),
        ("LIST order type", 'list-type="order"' in tagged),
        ("EQUATION fTAN", "fTAN" in tagged),
        ("REFERENCE", "<ref " in tagged),
        ("No thin-line fig", 'data-source="p6_b2"' not in tagged),
    ]
    for name, ok in checks:
        print(f"  {'OK' if ok else 'FAIL'}: {name}")

    print("\n=== Page 1 excerpt ===")
    start = tagged.find("<article")
    print(tagged[start : start + 2200])


if __name__ == "__main__":
    main()
