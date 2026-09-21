"""Tests for final XML serialization with hexadecimal quote entities."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody
from app.services.xml_generator import generate_jats_xml
from app.utils.xml_serializer import (
    XmlSerializationError,
    apply_final_xml_serialization_to_extraction_result,
    escape_for_xml_serialization,
    serialize_lxml_tree,
    serialize_xml_text_nodes_with_hex_quotes,
)

ROOT = Path(__file__).resolve().parent.parent
DTD_PATH = ROOT / "tests" / "fixtures" / "periodicals.dtd"


def test_escape_single_quotes_phrase() -> None:
    text = "''Explainable AI'' AND ''Breast Cancer''"
    assert escape_for_xml_serialization(text) == (
        "&#x27;&#x27;Explainable AI&#x27;&#x27; AND &#x27;&#x27;Breast Cancer&#x27;&#x27;"
    )


def test_escape_double_quotes_phrase() -> None:
    text = '"Explainable AI"'
    assert escape_for_xml_serialization(text) == "&#x22;Explainable AI&#x22;"


def test_escape_special_xml_characters() -> None:
    text = "A & B < C > D"
    assert escape_for_xml_serialization(text) == "A &amp; B &lt; C &gt; D"


def test_does_not_double_escape_existing_entities() -> None:
    already = "&#x27;Explainable AI&#x22;"
    element = etree.Element("p")
    element.text = already
    xml = serialize_lxml_tree(element, xml_declaration=False, pretty_print=False)
    assert xml == "<p>&amp;#x27;Explainable AI&amp;#x22;</p>"


def test_serialize_text_and_attribute_values() -> None:
    element = etree.Element("p", attrib={"label": '\'"quoted"\''})
    element.text = "''Explainable AI''"
    xml = serialize_lxml_tree(element, xml_declaration=False, pretty_print=False)
    assert xml == (
        "<p label=\"&#x27;&#x22;quoted&#x22;&#x27;\">"
        "&#x27;&#x27;Explainable AI&#x27;&#x27;</p>"
    )


def test_serialize_xml_text_nodes_with_hex_quotes() -> None:
    xml = "<p>''Explainable AI'' AND ''Breast Cancer''</p>"
    serialized = serialize_xml_text_nodes_with_hex_quotes(xml)
    assert (
        "<p>&#x27;&#x27;Explainable AI&#x27;&#x27; AND "
        "&#x27;&#x27;Breast Cancer&#x27;&#x27;</p>" in serialized.replace("\n", "")
    )


def test_generated_xml_parses_and_round_trips_quote_text() -> None:
    xml = b"""
    <article dtd-version="2.0" xml:lang="eng">
      <front>
        <journal-meta>
          <journal-id journal-id-type="ieee">0055400</journal-id>
          <journal-title-group><journal-title>IEEE Sensors Journal</journal-title></journal-title-group>
          <publisher><publisher-name>IEEE</publisher-name></publisher>
        </journal-meta>
        <article-meta>
          <article-id pub-id-type="doi">10.1109/JSEN.2024.0000000</article-id>
          <title-group><article-title>Sample Article</article-title></title-group>
          <contrib-group>
            <contrib contrib-type="author">
              <name-alternatives><string-name><surname>Doe</surname></string-name></name-alternatives>
            </contrib>
          </contrib-group>
          <abstract><p>''Explainable AI'' AND ''Breast Cancer''</p></abstract>
        </article-meta>
      </front>
      <body>
        <sec id="sec1"><title>Introduction</title><p>"Explainable AI"</p></sec>
      </body>
      <back>
        <ref-list>
          <ref id="ref1"><mixed-citation>A &amp; B &lt; C &gt; D</mixed-citation></ref>
        </ref-list>
      </back>
    </article>
    """
    document = etree.fromstring(xml)
    paragraph = document.find(".//abstract/p")
    assert paragraph is not None
    paragraph.text = "''Explainable AI'' AND ''Breast Cancer''"
    body_p = document.find(".//body/sec/p")
    assert body_p is not None
    body_p.text = '"Explainable AI"'
    mixed = document.find(".//mixed-citation")
    assert mixed is not None
    mixed.text = "A & B < C > D"

    serialized = serialize_lxml_tree(document, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    assert "&#x27;&#x27;Explainable AI&#x27;&#x27;" in serialized
    assert "&#x22;Explainable AI&#x22;" in serialized
    assert "A &amp; B &lt; C &gt; D" in serialized
    assert "&amp;#x27;" not in serialized

    reparsed = etree.fromstring(serialized.encode("utf-8"))
    abstract_p = reparsed.find(".//{*}abstract/{*}p")
    body_p = reparsed.find(".//{*}body/{*}sec/{*}p")
    mixed = reparsed.find(".//{*}mixed-citation")
    assert abstract_p is not None and abstract_p.text == "''Explainable AI'' AND ''Breast Cancer''"
    assert body_p is not None and body_p.text == '"Explainable AI"'
    assert mixed is not None and mixed.text == "A & B < C > D"


def test_apply_final_xml_serialization_to_extraction_result() -> None:
    result = {
        "pages": [{"blocks": [{"text": "''Explainable AI''"}]}],
        "structure": {
            "semantic": {
                "tagged_output": "<p>''Explainable AI'' AND ''Breast Cancer''</p>",
            }
        },
    }
    serialized = apply_final_xml_serialization_to_extraction_result(result)
    tagged = serialized["structure"]["semantic"]["tagged_output"]
    assert "&#x27;&#x27;Explainable AI&#x27;&#x27;" in tagged
    assert result["structure"]["semantic"]["tagged_output"] == (
        "<p>''Explainable AI'' AND ''Breast Cancer''</p>"
    )
    assert result["pages"][0]["blocks"][0]["text"] == "''Explainable AI''"


def test_round_trip_serialization_does_not_double_encode_quotes() -> None:
    xml = "<p>''Explainable AI'' AND ''Breast Cancer''</p>"
    once = serialize_xml_text_nodes_with_hex_quotes(xml)
    twice = serialize_xml_text_nodes_with_hex_quotes(once)
    assert once.replace("\n", "") == twice.replace("\n", "")
    assert "&amp;#x27;" not in twice


def test_serialized_quote_xml_validates_against_dtd() -> None:
    """Test 5: generated XML with hex quote entities parses and validates against DTD."""
    dtd = etree.DTD(str(DTD_PATH))
    xml = b"""
    <article dtd-version="2.0" xml:lang="eng">
      <front>
        <journal-meta>
          <journal-id journal-id-type="ieee">0055400</journal-id>
          <journal-title-group><journal-title>IEEE Sensors Journal</journal-title></journal-title-group>
          <publisher><publisher-name>IEEE</publisher-name></publisher>
        </journal-meta>
        <article-meta>
          <article-id pub-id-type="doi">10.1109/JSEN.2024.0000000</article-id>
          <title-group><article-title>Sample Article</article-title></title-group>
          <contrib-group>
            <contrib contrib-type="author">
              <name-alternatives><string-name><surname>Doe</surname></string-name></name-alternatives>
            </contrib>
          </contrib-group>
          <abstract><p>placeholder</p></abstract>
        </article-meta>
      </front>
      <body>
        <sec id="sec1"><title>Introduction</title><p>Body text.</p></sec>
      </body>
      <back>
        <ref-list>
          <ref id="ref1"><mixed-citation>Reference text.</mixed-citation></ref>
        </ref-list>
      </back>
    </article>
    """
    document = etree.fromstring(xml)
    paragraph = document.find(".//abstract/p")
    assert paragraph is not None
    paragraph.text = "''Explainable AI'' AND ''Breast Cancer''"

    serialized = serialize_lxml_tree(document, xml_declaration=False, pretty_print=True)
    assert "&#x27;&#x27;Explainable AI&#x27;&#x27;" in serialized
    assert "&amp;#x27;" not in serialized

    reparsed = etree.fromstring(serialized.encode("utf-8"))
    assert reparsed.get("{http://www.w3.org/XML/1998/namespace}lang") == "eng"
    assert dtd.validate(reparsed), dtd.error_log.filter_from_errors()


def test_serialize_xml_comment_node() -> None:
    root = etree.fromstring(
        b"<article><!-- IEEE JATS reference template metadata --><p>''Explainable AI''</p></article>"
    )
    serialized = serialize_lxml_tree(root, xml_declaration=False, pretty_print=False)
    assert "<!-- IEEE JATS reference template metadata -->" in serialized
    assert "&#x27;&#x27;Explainable AI&#x27;&#x27;" in serialized


def test_serialize_processing_instruction_node() -> None:
    root = etree.fromstring(
        b"""<article>
          <?xml-stylesheet type="text/xsl" href="article.xsl"?>
          <p>"Explainable AI"</p>
        </article>"""
    )
    serialized = serialize_lxml_tree(root, xml_declaration=False, pretty_print=True)
    assert '<?xml-stylesheet type="text/xsl" href="article.xsl"?>' in serialized
    assert "&#x22;Explainable AI&#x22;" in serialized


def test_serialize_namespaced_attribute_and_element_text() -> None:
    root = etree.fromstring(
        b"<article dtd-version=\"2.0\" xml:lang=\"eng\"><p>''Explainable AI''</p></article>"
    )
    serialized = serialize_lxml_tree(root, xml_declaration=False, pretty_print=False)
    assert 'xml:lang="eng"' in serialized
    assert "&#x27;&#x27;Explainable AI&#x27;&#x27;" in serialized


def test_xlink_graphic_declares_namespace_and_parses(tmp_path: Path) -> None:
    """Test A: xlink:href requires xmlns:xlink on the document root."""
    root = etree.Element("article")
    graphic = etree.SubElement(root, "graphic")
    graphic.set("{http://www.w3.org/1999/xlink}href", "figure1.png")

    serialized = serialize_lxml_tree(root, xml_declaration=False, pretty_print=False)
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in serialized
    assert 'xlink:href="figure1.png"' in serialized
    assert "&amp;#x27;" not in serialized

    reparsed = etree.fromstring(serialized.encode("utf-8"))
    assert reparsed.nsmap.get("xlink") == "http://www.w3.org/1999/xlink"
    assert reparsed.find("graphic").get("{http://www.w3.org/1999/xlink}href") == "figure1.png"


def test_serialize_does_not_emit_whitespace_only_lines() -> None:
    """Template formatting whitespace must not become blank lines in output."""
    xml = b"""<article>
  <front>

    <journal-meta>

      <journal-title>Test</journal-title>

    </journal-meta>

  </front>
</article>"""
    root = etree.fromstring(xml, etree.XMLParser(remove_blank_text=True))
    serialized = serialize_lxml_tree(root, xml_declaration=False, pretty_print=True)
    for line in serialized.splitlines():
        assert line.strip(), f"whitespace-only line in output: {line!r}"
    assert "<front>" in serialized
    assert "  <journal-meta>" in serialized


def test_escape_non_ascii_characters_as_hex_entities() -> None:
    assert escape_for_xml_serialization("café") == "caf&#x00E9;"
    assert escape_for_xml_serialization("José García") == "Jos&#x00E9; Garc&#x00ED;a"
    assert escape_for_xml_serialization("μ") == "&#x03BC;"
    assert (
        escape_for_xml_serialization("Universit\u00e1 di Verona")
        == "Universit&#x00E1; di Verona"
    )


def test_escape_ampersand_only() -> None:
    """Test D."""
    assert escape_for_xml_serialization("A & B") == "A &amp; B"


def test_escape_less_and_greater_than() -> None:
    """Test E."""
    assert escape_for_xml_serialization("A < B > C") == "A &lt; B &gt; C"


def test_escape_combined_quotes_and_ampersand() -> None:
    """Test F."""
    text = "''Explainable AI'' AND \"Breast Cancer\" & XAI"
    assert escape_for_xml_serialization(text) == (
        "&#x27;&#x27;Explainable AI&#x27;&#x27; AND &#x22;Breast Cancer&#x22; &amp; XAI"
    )


def test_fixture_template_preserves_xlink_and_mml_namespaces() -> None:
    fixture = ROOT / "tests" / "fixtures" / "1458242.xml"
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="''Explainable AI'' AND ''Breast Cancer''",
                source_block_ids=["p1"],
            ),
            MappedSemanticNode(
                semantic_type="figure",
                label="Fig. 1.",
                source_block_ids=["p2"],
                children=[
                    MappedSemanticNode(
                        semantic_type="caption",
                        text='"Explainable AI" caption',
                        source_block_ids=["p2"],
                    )
                ],
            ),
        ],
        back={},
    )
    xml = generate_jats_xml(fixture, mapping)
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in xml
    assert 'xmlns:mml="http://www.w3.org/1998/Math/MathML"' in xml
    assert 'xlink:href="fig1.eps"' in xml
    assert (
        "&#x27;&#x27;Explainable AI&#x27;&#x27; AND &#x27;&#x27;Breast Cancer&#x27;&#x27;" in xml
    )
    assert "&#x22;Explainable AI&#x22;" in xml
    assert "&amp;#x27;" not in xml

    reparsed = etree.fromstring(xml.encode("utf-8"))
    assert reparsed.nsmap.get("xlink") == "http://www.w3.org/1999/xlink"


def test_generate_jats_xml_with_template_comments(tmp_path: Path) -> None:
    """Regression for 500 when IEEE templates contain XML comments as child nodes."""
    template = tmp_path / "template_with_comment.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article dtd-version="2.0" xml:lang="eng">
  <!-- IEEE JATS reference template metadata -->
  <?xml-stylesheet type="text/xsl" href="article.xsl"?>
  <front>
    <article-meta>
      <title-group><article-title>Title</article-title></title-group>
    </article-meta>
  </front>
  <body></body>
  <back></back>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="''Explainable AI'' AND ''Breast Cancer''",
                source_block_ids=["p1_b1"],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert "<!-- IEEE JATS reference template metadata -->" in xml
    assert '<?xml-stylesheet type="text/xsl" href="article.xsl"?>' in xml
    assert (
        "&#x27;&#x27;Explainable AI&#x27;&#x27; AND &#x27;&#x27;Breast Cancer&#x27;&#x27;" in xml
    )
    assert "&amp;#x27;" not in xml


def test_unsupported_node_raises_clear_error() -> None:
    root = etree.Element("article")
    entity = etree.Entity("nbsp")
    root.append(entity)
    with pytest.raises(XmlSerializationError, match="Unsupported XML node type"):
        serialize_lxml_tree(root, xml_declaration=False, pretty_print=False)


def test_periodicals_dtd_fixture_still_validates() -> None:
    """Confirm DTD validation flow used by the project still passes on fixture XML."""
    dtd = etree.DTD(str(DTD_PATH))
    xml = b"""
    <article dtd-version="2.0" xml:lang="eng">
      <front>
        <journal-meta>
          <journal-id journal-id-type="ieee">0055400</journal-id>
          <journal-title-group><journal-title>IEEE Sensors Journal</journal-title></journal-title-group>
          <publisher><publisher-name>IEEE</publisher-name></publisher>
        </journal-meta>
        <article-meta>
          <article-id pub-id-type="doi">10.1109/JSEN.2024.0000000</article-id>
          <title-group><article-title>Sample Article</article-title></title-group>
          <contrib-group>
            <contrib contrib-type="author">
              <name-alternatives><string-name><surname>Doe</surname></string-name></name-alternatives>
            </contrib>
          </contrib-group>
          <abstract><p>Abstract text.</p></abstract>
        </article-meta>
      </front>
      <body>
        <sec id="sec1"><title>Introduction</title><p>Body text.</p></sec>
      </body>
      <back>
        <ref-list>
          <ref id="ref1"><mixed-citation>Reference text.</mixed-citation></ref>
        </ref-list>
      </back>
    </article>
    """
    document = etree.fromstring(xml)
    assert dtd.validate(document), dtd.error_log.filter_from_errors()
