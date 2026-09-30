"""Regression: output = template structure + PDF content (not sample XML text)."""

import pytest
from lxml import etree

from app.agent.xml_generator import XMLGenerator, _generate_from_template_dom
from app.llm.client import LLMClient
from app.models.mapping_plan import MappingEntry, MappingPlan
from app.models.paper import Author, PaperData, Reference, Section
from app.utils.template_skeleton import prepare_template_for_pdf_content

SAMPLE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:mml="http://www.w3.org/1998/Math/MathML">
  <front>
    <article-meta>
      <title-group>
        <article-title>Sample Article Title</article-title>
      </title-group>
      <contrib-group>
        <contrib id="contrib1" contrib-type="author">
          <string-name><given-names>Sample</given-names><surname>Author</surname></string-name>
        </contrib>
        <contrib id="contrib2" contrib-type="author">
          <string-name><given-names>Sample</given-names><surname>Author Two</surname></string-name>
        </contrib>
      </contrib-group>
      <abstract><p>This is sample abstract content from the template.</p></abstract>
      <kwd-group><kwd>sample-keyword</kwd></kwd-group>
    </article-meta>
  </front>
  <body>
    <sec id="sec1"><title>Sample Section</title><p>This is sample content.</p></sec>
  </body>
  <back>
    <ref-list>
      <ref id="ref1"><label>[1]</label><mixed-citation><p>Sample reference text.</p></mixed-citation></ref>
    </ref-list>
  </back>
</article>"""


def _full_plan() -> MappingPlan:
    return MappingPlan(
        mappings=[
            MappingEntry(
                xml_xpath="front/article-meta/title-group/article-title",
                xml_tag="article-title",
                pdf_field="title",
                transform="none",
                confidence=1.0,
                reasoning="t",
            ),
            MappingEntry(
                xml_xpath="front/article-meta/abstract",
                xml_tag="abstract",
                pdf_field="abstract",
                transform="none",
                confidence=1.0,
                reasoning="a",
            ),
            MappingEntry(
                xml_xpath="front/article-meta/contrib-group/contrib",
                xml_tag="contrib",
                pdf_field="authors[]",
                transform="loop",
                confidence=1.0,
                reasoning="authors",
            ),
        ]
    )


def _pdf_paper() -> PaperData:
    return PaperData(
        title="Actual Paper Title",
        abstract="This is the actual abstract from the PDF.",
        authors=[
            Author(first_name="John", last_name="Smith", full_name="John Smith"),
            Author(first_name="Jane", last_name="Doe", full_name="Jane Doe"),
        ],
        keywords=["pdf-keyword"],
        sections=[
            Section(
                id="sec1",
                label="1.",
                title="Introduction",
                level=1,
                paragraphs=["This is the actual introduction from the PDF."],
            ),
            Section(
                id="sec2",
                label="2.",
                title="Methodology",
                level=1,
                paragraphs=["This is the actual methodology from the PDF."],
            ),
        ],
        references=[
            Reference(id="ref1", number=1, raw_text="PDF Reference One"),
        ],
    )


@pytest.mark.asyncio
async def test_dom_generation_replaces_sample_with_pdf_content():
    out = _generate_from_template_dom(SAMPLE_TEMPLATE, _pdf_paper(), _full_plan())
    etree.fromstring(out.encode("utf-8"))

    assert "Actual Paper Title" in out
    assert "John" in out and "Smith" in out
    assert "Jane" in out and "Doe" in out
    assert "actual introduction from the PDF" in out
    assert "actual methodology from the PDF" in out
    assert "PDF Reference One" in out
    assert "pdf-keyword" in out

    assert "Sample Article Title" not in out
    assert "Sample Author" not in out
    assert "sample abstract content" not in out
    assert "Sample Section" not in out
    assert "This is sample content." not in out
    assert "Sample reference text" not in out
    assert "sample-keyword" not in out


@pytest.mark.asyncio
async def test_xml_generator_async_path_same_as_dom():
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    out = await XMLGenerator(llm).generate(SAMPLE_TEMPLATE, _pdf_paper(), _full_plan())
    assert "Actual Paper Title" in out
    assert "Sample Article Title" not in out


def test_prepare_template_clears_article_meta_but_keeps_journal_meta():
    tpl = """<article><front>
    <journal-meta><journal-title>IEEE Sample Journal</journal-title></journal-meta>
    <article-meta><article-title>Demo Title</article-title></article-meta>
    </front></article>"""
    root = etree.fromstring(tpl.encode())
    prepare_template_for_pdf_content(root)
    xml = etree.tostring(root, encoding="unicode")
    assert "IEEE Sample Journal" in xml
    assert "Demo Title" not in xml
