import pytest

from app.agent.reference_parser import ReferenceParser
from app.llm.client import LLMClient

RAW = [
    "[1] H. Sung et al., Global Cancer Statistics, CA Cancer J. Clin., vol. 71, pp. 209-249, 2021.",
    "[2] A. Author, Sample paper title, IEEE Access, vol. 9, pp. 1-10, 2021.",
    "[3] B. Writer and C. Coauthor, Another study, Nature, vol. 100, pp. 50-60, 2020.",
]


@pytest.mark.asyncio
async def test_reference_parser_three_refs():
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    parser = ReferenceParser(llm)
    refs = await parser.parse(RAW)
    assert len(refs) == 3
    for r in refs:
        assert r.parsed is not None
        authors = r.parsed.get("authors", [])
        assert authors and "surname" in authors[0]
