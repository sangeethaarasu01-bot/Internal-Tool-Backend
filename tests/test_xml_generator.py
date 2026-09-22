import pytest
from lxml import etree

from app.agent.xml_generator import XMLGenerator
from app.llm.client import LLMClient
from app.models.mapping_plan import MappingEntry, MappingPlan
from app.models.paper import Author, PaperData

SAMPLE_XML = """<?xml version="1.0"?><article><front><article-meta>
<title-group><article-title></article-title></title-group>
<abstract></abstract>
</article-meta></front></article>"""


@pytest.mark.asyncio
async def test_fill_authors_unique_contrib_ids():
    from lxml import etree

    from app.agent.xml_generator import _fill_authors
    from app.models.paper import Author

    tpl = """<article><front><article-meta><contrib-group>
    <contrib id="contrib1" contrib-type="author"><string-name>A</string-name></contrib>
    <contrib id="contrib2" contrib-type="author"><string-name>B</string-name></contrib>
    </contrib-group></article-meta></front>
    <back><bio><p><xref ref-type="contrib" rid="contrib3">Name</xref></p></bio></back>
    </article>"""
    root = etree.fromstring(tpl.encode())
    authors = [
        Author(full_name=f"Author {i}", first_name="A", last_name=str(i)) for i in range(1, 4)
    ]
    _fill_authors(root, authors)
    xml = etree.tostring(root, encoding="unicode")
    assert 'id="contrib1"' in xml
    assert 'id="contrib2"' in xml
    assert 'id="contrib3"' in xml
    assert 'rid="contrib3"' in xml


def test_fill_authors_uses_each_template_contrib_not_first_only():
    from app.agent.xml_generator import _fill_authors

    tpl = """<article><front><article-meta><contrib-group>
    <contrib id="contrib1" contrib-type="author">
      <name-alternatives>
        <string-name specific-use="display"><given-names>Template1</given-names><surname>One</surname></string-name>
        <string-name specific-use="index"><given-names>Template1</given-names><surname>One</surname></string-name>
      </name-alternatives>
      <email>one@example.com</email>
      <xref ref-type="bio" rid="bio1"/>
    </contrib>
    <contrib id="contrib2" contrib-type="author">
      <name-alternatives>
        <string-name specific-use="display"><given-names>Template2</given-names><surname>Two</surname></string-name>
        <string-name specific-use="index"><given-names>Template2</given-names><surname>Two</surname></string-name>
      </name-alternatives>
      <email>two@example.com</email>
      <xref ref-type="bio" rid="bio2"/>
    </contrib>
    </contrib-group></article-meta></front></article>"""
    root = etree.fromstring(tpl.encode())
    authors = [
        Author(first_name="Madhurima", last_name="Moulick", full_name="Madhurima Moulick"),
        Author(
            first_name="Sagar",
            last_name="Chowdhury",
            full_name="Sagar Chowdhury",
            email="syncwithsagar@gmail.com",
        ),
    ]
    _fill_authors(root, authors)
    xml = etree.tostring(root, encoding="unicode")
    assert "Madhurima" in xml and "Moulick" in xml
    assert "Sagar" in xml and "Chowdhury" in xml
    assert "Madhurima<given-names>" not in xml.replace("\n", "").replace(" ", "")
    contribs = root.xpath(".//*[local-name()='contrib']")
    assert len(contribs) == 2
    c2_given = contribs[1].xpath(".//*[local-name()='given-names']")
    assert c2_given and (c2_given[0].text or "").strip() == "Sagar"
    c2_email = contribs[1].xpath(".//*[local-name()='email']")
    assert c2_email and c2_email[0].text == "syncwithsagar@gmail.com"
    c2_bio = contribs[1].xpath(".//*[local-name()='xref' and @ref-type='bio']")
    assert c2_bio and c2_bio[0].get("rid") == "bio2"


@pytest.mark.asyncio
async def test_xml_generator_valid_output():
    paper = PaperData(
        title="Test Title",
        abstract="Test abstract",
        authors=[Author(full_name="Jane Doe", first_name="Jane", last_name="Doe")],
    )
    plan = MappingPlan(
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
        ]
    )
    llm = LLMClient(provider="anthropic", model="mock", api_key="")
    gen = XMLGenerator(llm)
    out = await gen.generate(SAMPLE_XML, paper, plan)
    root = etree.fromstring(out.encode("utf-8"))
    titles = root.xpath(".//*[local-name()='article-title']")
    assert titles and (titles[0].text or "").strip() == "Test Title"
