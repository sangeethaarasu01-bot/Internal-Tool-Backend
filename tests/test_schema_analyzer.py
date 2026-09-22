import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from lxml import etree

from app.agent.schema_analyzer import SchemaAnalyzer, _build_schema_from_tree
from app.llm.client import LLMClient, LLMResponse

SAMPLE_XML = Path(__file__).resolve().parent.parent / "data" / "samples" / "1458251.xml"


@pytest.mark.asyncio
async def test_schema_analyzer_mock_llm():
    tree = etree.parse(str(SAMPLE_XML))
    big_elements = []
    for i in range(55):
        big_elements.append(
            {
                "xpath": f"article/meta/field{i}",
                "tag": f"field{i}",
                "semantic": "unknown",
                "cardinality": "single",
                "data_type": "string",
                "required": False,
                "attributes": {},
                "sample": "",
                "children": [],
                "notes": "",
            }
        )
    mock_resp = LLMResponse(
        text=json.dumps(
            {
                "root_tag": "article",
                "namespaces": {},
                "doctype": None,
                "elements": big_elements,
            }
        ),
        tokens_in=100,
        tokens_out=200,
        cost_usd=0.01,
        model="mock",
    )
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    llm.complete = AsyncMock(return_value=mock_resp)
    analyzer = SchemaAnalyzer(llm)
    schema = await analyzer.analyze(SAMPLE_XML)
    assert schema.root_tag == "article"
    assert len(schema.elements) > 50


def test_build_schema_from_tree():
    tree = etree.parse(str(SAMPLE_XML))
    schema = _build_schema_from_tree(tree, "hash")
    assert schema.root_tag == "article"
