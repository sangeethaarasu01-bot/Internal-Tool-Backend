"""Create a small digital (text) PDF and run Stage 1 extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from app.services.text_extractor import extract_text_layout

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "digital_ieee_sample.pdf"
SAMPLE_JSON = ROOT / "tests" / "fixtures" / "digital_ieee_sample.extraction.json"


def write_fixture() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "IEEE Sensors Journal", fontsize=11, fontname="helv")
    page.insert_text(
        (72, 110),
        "A Customized Electronic Tongue for Tea Quality Evaluation",
        fontsize=16,
        fontname="helv",
    )
    page.insert_text((72, 140), "Madhurima Moulick and Runu Banerjee Roy", fontsize=11, fontname="helv")
    page.insert_text(
        (72, 180),
        "Abstract - A voltammetric electronic tongue consisting of MIP electrodes "
        "detects theophylline, tannic acid, and theaflavins in black tea.",
        fontsize=10,
        fontname="helv",
    )
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 72), "I. Introduction", fontsize=14, fontname="helv")
    page2.insert_text(
        (72, 110),
        "Tea quality assessment is often subjective. This paper describes a sensor array "
        "and switching circuit under the same experimental conditions.",
        fontsize=10,
        fontname="helv",
    )
    doc.set_metadata(
        {
            "title": "A Customized Electronic Tongue for Tea Quality Evaluation",
            "author": "Madhurima Moulick",
            "creator": "Stage1Fixture",
            "producer": "pymupdf",
        }
    )
    doc.save(FIXTURE)
    doc.close()


def main() -> None:
    write_fixture()
    result = extract_text_layout(str(FIXTURE), original_filename=FIXTURE.name)
    payload = result.model_dump()
    SAMPLE_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    page = payload["pages"][0]
    block = page["blocks"][0]
    line = block["lines"][0]
    span = line["spans"][0]
    print("fixture", FIXTURE)
    print("pages", payload["document"]["page_count"])
    print("requires_ocr", payload["document"]["requires_ocr"])
    print("ocr_applied", payload["document"]["ocr_applied"])
    print("stats", payload["stats"])
    print("sample_span", json.dumps(span))
    print("sample_block_bbox", block["bbox"])
    print("mongo_skip", "live insert skipped during review (Atlas timeout)")


if __name__ == "__main__":
    main()
