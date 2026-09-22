from pathlib import Path

import pymupdf as fitz
import pytest

from app.agent.pdf_extractor import PDFExtractor
from app.llm.client import LLMClient

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "data" / "samples" / "access-khan-3639184-proof1.pdf"


@pytest.fixture(scope="module", autouse=True)
def ensure_sample_pdf():
    if not SAMPLE_PDF.exists():
        import sys

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root))
        from scripts.generate_sample_pdf import main

        main()


def test_extract_multiline_ieee_title():
    """IEEE Sensors-style titles span several lines at the same large font size."""
    expected = (
        "A Customized Electronic Tongue by Developing an Array of "
        "Molecular Imprinted Polymer-Based Voltammetric Electrodes for "
        "Tea Quality Evaluation"
    )
    title_lines = [
        "A Customized Electronic Tongue by Developing",
        "an Array of Molecular Imprinted Polymer-Based",
        "Voltammetric Electrodes for Tea",
        "Quality Evaluation",
    ]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 120
    for line in title_lines:
        page.insert_text((72, y), line, fontsize=18)
        y += 22
    page.insert_text((72, y + 10), "Madhurima Moulick, Sagar Chowdhury", fontsize=10)
    extractor = PDFExtractor(LLMClient(provider="anthropic", model="mock", api_key=""))
    assert extractor._extract_title(doc) == expected
    doc.close()


@pytest.mark.asyncio
async def test_pdf_extractor_sample():
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    extractor = PDFExtractor(llm)
    paper = await extractor.extract(SAMPLE_PDF)
    assert "Breast Cancer Diagnosis" in paper.title
    assert len(paper.authors) == 5
    assert len(paper.sections) >= 7
