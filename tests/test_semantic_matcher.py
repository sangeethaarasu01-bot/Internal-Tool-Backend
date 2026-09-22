import json
from unittest.mock import AsyncMock

import pytest

from app.agent.semantic_matcher import SemanticMatcher
from app.llm.client import LLMClient, LLMResponse
from app.models.paper import PaperData
from app.models.schema_map import SchemaElement, SchemaMap


@pytest.mark.asyncio
async def test_semantic_matcher_title_authors_abstract():
    schema = SchemaMap(
        root_tag="article",
        elements=[
            SchemaElement(
                xpath="front/article-meta/title-group/article-title",
                tag="article-title",
                semantic="paper_title",
                cardinality="single",
                data_type="string",
                required=True,
            ),
            SchemaElement(
                xpath="front/article-meta/contrib-group/contrib",
                tag="contrib",
                semantic="author_name",
                cardinality="repeating",
                data_type="string",
                required=True,
            ),
            SchemaElement(
                xpath="front/article-meta/abstract",
                tag="abstract",
                semantic="abstract",
                cardinality="single",
                data_type="string",
                required=True,
            ),
        ],
        template_hash="x",
    )
    paper = PaperData(title="T", abstract="A", authors=[])
    mock_resp = LLMResponse(
        text=json.dumps(
            {
                "mappings": [
                    {
                        "xml_xpath": "front/article-meta/title-group/article-title",
                        "xml_tag": "article-title",
                        "pdf_field": "title",
                        "transform": "none",
                        "transform_arg": None,
                        "confidence": 0.99,
                        "reasoning": "ok",
                    },
                    {
                        "xml_xpath": "front/article-meta/contrib-group/contrib",
                        "xml_tag": "contrib",
                        "pdf_field": "authors[]",
                        "transform": "loop",
                        "transform_arg": None,
                        "confidence": 0.9,
                        "reasoning": "ok",
                    },
                    {
                        "xml_xpath": "front/article-meta/abstract",
                        "xml_tag": "abstract",
                        "pdf_field": "abstract",
                        "transform": "none",
                        "transform_arg": None,
                        "confidence": 0.9,
                        "reasoning": "ok",
                    },
                ],
                "unmapped_xml": [],
                "unmapped_pdf": [],
                "warnings": [],
            }
        ),
        tokens_in=1,
        tokens_out=1,
        cost_usd=0,
        model="mock",
    )
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    llm.complete = AsyncMock(return_value=mock_resp)
    matcher = SemanticMatcher(llm)
    plan = await matcher.match(schema, paper)
    fields = {m.pdf_field for m in plan.mappings}
    assert "title" in fields
    assert "authors[]" in fields
    assert "abstract" in fields
