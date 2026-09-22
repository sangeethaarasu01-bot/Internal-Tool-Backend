from pathlib import Path

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


@pytest.mark.asyncio
async def test_pdf_extractor_sample():
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    extractor = PDFExtractor(llm)
    paper = await extractor.extract(SAMPLE_PDF)
    assert "Breast Cancer Diagnosis" in paper.title
    assert len(paper.authors) == 5
    assert len(paper.sections) >= 7
