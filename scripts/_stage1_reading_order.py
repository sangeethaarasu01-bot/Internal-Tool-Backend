"""Temporary Stage 1 reading-order validation. Not part of the product."""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from app.services.text_extractor import extract_text_layout

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
GUTTER = 18.0
HEADER_Y_MAX = 50.0
FOOTER_Y_MARGIN = 40.0

RUNNING_HEADER_RE = re.compile(
    r"^(?:\d+\s+)?IEEE\s+SENSORS\s+JOURNAL(?:\s+\d+)?$",
    re.IGNORECASE,
)
AUTHOR_RUNNING_HEADER_RE = re.compile(
    r"MOULICK\s+et\s+al\.:.*CUSTOMIZED\s+e-TONGUE",
    re.IGNORECASE,
)
FOOTER_RE = re.compile(
    r"(all rights reserved|ieee\.org|publications/rights)",
    re.IGNORECASE,
)
CITATION_RE = re.compile(
    r"(?:\[\d+\]|doi:\s*10\.|vol\.\s*\d+|pp\.\s*\d|IEEE\s+Sensors\s+J\.)",
    re.IGNORECASE,
)


def classify_column(bbox: list[float], page_width: float) -> str:
    x0, _y0, x1, _y1 = bbox
    mid = page_width / 2.0
    if x0 < mid - GUTTER and x1 > mid + GUTTER:
        return "FULL_WIDTH"
    if x0 >= mid - GUTTER:
        return "RIGHT"
    return "LEFT"


def preview(text: str, n: int = 100) -> str:
    return (text or "").replace("\n", " ")[:n]


def find_ieee_proof_pdf() -> Path:
    if not UPLOADS_DIR.is_dir():
        raise FileNotFoundError(f"Uploads directory not found: {UPLOADS_DIR}")

    jsen_proofs = sorted(
        UPLOADS_DIR.glob("*jsen-banerjeeroy*proof1.pdf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if jsen_proofs:
        return jsen_proofs[0]

    any_proofs = sorted(
        UPLOADS_DIR.glob("*proof1.pdf"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if any_proofs:
        return any_proofs[0]

    raise FileNotFoundError(f"No IEEE proof PDF found in {UPLOADS_DIR}")


def block_char_offsets(pages) -> dict[str, int]:
    offsets: dict[str, int] = {}
    pos = 0
    for page in pages:
        for block in page.blocks:
            offsets[block.block_id] = pos
            pos += len(block.text or "") + 1
    return offsets


def classify_block_role(
    block,
    page,
    refs_pos: int,
    offsets: dict[str, int],
) -> str:
    text = (block.text or "").strip()
    if not text:
        return "BODY_TEXT"

    y0, y1 = block.bbox[1], block.bbox[3]
    near_top = y0 < HEADER_Y_MAX
    near_bottom = y1 > page.height - FOOTER_Y_MARGIN
    flat = text.replace("\n", " ").strip()
    in_refs = refs_pos >= 0 and offsets.get(block.block_id, -1) >= refs_pos
    looks_like_citation = bool(CITATION_RE.search(text))

    if near_top:
        if RUNNING_HEADER_RE.match(flat):
            return "RUNNING_HEADER"
        if AUTHOR_RUNNING_HEADER_RE.search(flat):
            return "RUNNING_HEADER"
        if re.fullmatch(r"\d{1,3}", flat):
            return "PAGE_NUMBER"

    if in_refs or looks_like_citation:
        return "REFERENCE_TEXT"

    if near_bottom and FOOTER_RE.search(text):
        return "FOOTER"

    return "BODY_TEXT"


def is_header_footer_candidate(block, page) -> bool:
    text = (block.text or "").strip()
    if not text:
        return False
    y0, y1 = block.bbox[1], block.bbox[3]
    near_top = y0 < HEADER_Y_MAX
    near_bottom = y1 > page.height - FOOTER_Y_MARGIN
    if near_top and (
        "IEEE" in text
        or "SENSORS" in text
        or "MOULICK" in text
        or re.fullmatch(r"\d{1,3}", text.replace("\n", " ").strip())
    ):
        return True
    if near_bottom and FOOTER_RE.search(text):
        return True
    if near_bottom and CITATION_RE.search(text):
        return True
    return False


def detect_two_column_pages(pages) -> bool:
    for page in pages:
        text_blocks = [
            b for b in page.blocks if b.type == "text" and (b.text or "").strip()
        ]
        columns = {classify_column(b.bbox, page.width) for b in text_blocks}
        if "LEFT" in columns and "RIGHT" in columns:
            return True
    return False


def run_pytest() -> tuple[str, bool]:
    backend_dir = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    summary = ""
    for line in reversed((proc.stdout or "").splitlines()):
        stripped = line.strip()
        if stripped and ("passed" in stripped or "failed" in stripped or "error" in stripped):
            summary = stripped
            break
    if not summary:
        summary = "no pytest summary"
    return summary, proc.returncode == 0


def main() -> None:
    pdf = find_ieee_proof_pdf()
    result = extract_text_layout(str(pdf.resolve()))
    offsets = block_char_offsets(result.pages)

    right_before_unfinished_left: list[tuple[int, list[str]]] = []
    column_jump_pages: list[int] = []
    header_footer_candidates: list[tuple[int, str, str, list[float], str]] = []
    misclassified: list[str] = []
    reference_misclassified: list[str] = []

    for page in result.pages:
        text_blocks = [
            b for b in page.blocks if b.type == "text" and (b.text or "").strip()
        ]
        classes = [classify_column(b.bbox, page.width) for b in text_blocks]

        seen_right = False
        leftover_left: list[str] = []
        for b, col in zip(text_blocks, classes, strict=True):
            if col == "RIGHT":
                seen_right = True
            elif col == "LEFT" and seen_right:
                leftover_left.append(b.block_id)
        if leftover_left:
            right_before_unfinished_left.append((page.page_number, leftover_left))
            column_jump_pages.append(page.page_number)

    joined = "\n".join(b.text for pg in result.pages for b in pg.blocks)
    intro_pos = joined.find("INTRODUCTION")
    refs_pos = joined.find("REFERENCES")

    role_by_id: dict[str, str] = {}
    for page in result.pages:
        for block in page.blocks:
            if block.type != "text" or not (block.text or "").strip():
                continue
            role = classify_block_role(block, page, refs_pos, offsets)
            role_by_id[block.block_id] = role
            if not is_header_footer_candidate(block, page):
                continue
            header_footer_candidates.append(
                (
                    page.page_number,
                    block.block_id,
                    role,
                    block.bbox,
                    preview(block.text, 200),
                )
            )

    running_header_ids = ("p2_b0", "p4_b0", "p6_b0")
    for block_id in running_header_ids:
        actual = role_by_id.get(block_id)
        if actual not in {"RUNNING_HEADER", "PAGE_NUMBER"}:
            misclassified.append(
                f"{block_id}: expected RUNNING_HEADER/PAGE_NUMBER, got {actual or 'missing'}"
            )

    p7_b19_actual = role_by_id.get("p7_b19")
    if p7_b19_actual == "FOOTER":
        misclassified.append("p7_b19: reference text incorrectly classified as FOOTER")
        reference_misclassified.append("p7_b19 classified as FOOTER")
    elif p7_b19_actual not in {"REFERENCE_TEXT", "BODY_TEXT"}:
        misclassified.append(
            f"p7_b19: expected REFERENCE_TEXT/BODY_TEXT, got {p7_b19_actual or 'missing'}"
        )

    for block_id in ("p1_b16", "p1_b17"):
        actual = role_by_id.get(block_id)
        if actual != "FOOTER":
            misclassified.append(
                f"{block_id}: expected FOOTER, got {actual or 'missing'}"
            )

    block_text_by_id = {
        block.block_id: block.text or ""
        for page in result.pages
        for block in page.blocks
        if block.type == "text"
    }
    for block_id, role in role_by_id.items():
        block_text = block_text_by_id.get(block_id, "")
        in_refs = refs_pos >= 0 and offsets.get(block_id, -1) >= refs_pos
        looks_like_citation = bool(CITATION_RE.search(block_text))
        if role != "FOOTER":
            continue
        if in_refs or looks_like_citation:
            reference_misclassified.append(
                f"{block_id} reference/citation text classified as FOOTER"
            )

    dup_hits: list[tuple[int, list[str]]] = []
    for page in result.pages:
        texts = [
            " ".join((b.text or "").split())
            for b in page.blocks
            if b.type == "text" and len((b.text or "").strip()) > 40
        ]
        counts = Counter(texts)
        dups = [t[:80] for t, c in counts.items() if c > 1]
        if dups:
            dup_hits.append((page.page_number, dups))

    markers = {
        "INTRODUCTION": intro_pos >= 0,
        "REFERENCES": refs_pos >= 0,
        "theophylline": "theophylline" in joined.lower(),
        "tannic": "tannic" in joined.lower(),
        "Abstract": "Abstract" in joined,
    }

    reading_order = "FAIL" if right_before_unfinished_left else "PASS"
    column_detection = "PASS" if detect_two_column_pages(result.pages) else "FAIL"
    duplicate_text = "FAIL" if dup_hits else "PASS"
    text_completeness = "PASS" if all(markers.values()) else "FAIL"
    if intro_pos >= 0 and refs_pos >= 0 and refs_pos < intro_pos:
        text_completeness = "FAIL"
    header_footer_classification = "FAIL" if misclassified else "PASS"
    reference_text_classification = "FAIL" if reference_misclassified else "PASS"

    pytest_summary, pytest_ok = run_pytest()

    checks = {
        "reading_order": reading_order == "PASS",
        "column_detection": column_detection == "PASS",
        "text_completeness": text_completeness == "PASS",
        "duplicate_text": duplicate_text == "PASS",
        "header_footer_classification": header_footer_classification == "PASS",
        "reference_text_classification": reference_text_classification == "PASS",
        "pytest": pytest_ok,
    }
    overall = "STAGE 1 READY TO CLOSE" if all(checks.values()) else "FAIL"

    print("RIGHT_BEFORE_UNFINISHED_LEFT", right_before_unfinished_left or "NONE")
    print("COLUMN_JUMP_PAGES", column_jump_pages or "NONE")
    print("INTRO_POS", intro_pos)
    print("REFS_POS", refs_pos)
    print("MARKERS", markers)
    print("DUP_PAGES", dup_hits or "NONE")
    print("REFERENCE_TEXT_MISCLASSIFIED", reference_misclassified or "NONE")
    if misclassified:
        print("HEADER_FOOTER_MISCLASSIFIED", misclassified)
    print()
    print("## HEADER/FOOTER CANDIDATES")
    for page_no, block_id, role, bbox, text in header_footer_candidates:
        print(
            f"page={page_no} block_id={block_id} classification={role} "
            f"bbox=[{bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}] "
            f"text={text!r}"
        )
    print()
    print("STAGE 1 VALIDATION")
    print(f"PDF tested: {pdf.name}")
    print(f"PAGES: {result.document.page_count}")
    print(f"READING_ORDER: {reading_order}")
    print(f"COLUMN_DETECTION: {column_detection}")
    print(f"TEXT_COMPLETENESS: {text_completeness}")
    print(f"DUPLICATE_TEXT: {duplicate_text}")
    print(f"HEADER_FOOTER_CLASSIFICATION: {header_footer_classification}")
    print(f"p7_b19: {p7_b19_actual}")
    print(f"p2_b0: {role_by_id.get('p2_b0')}")
    print(f"p4_b0: {role_by_id.get('p4_b0')}")
    print(f"p6_b0: {role_by_id.get('p6_b0')}")
    print(f"PYTEST: {pytest_summary}")
    print(f"OVERALL: {overall}")


if __name__ == "__main__":
    main()
