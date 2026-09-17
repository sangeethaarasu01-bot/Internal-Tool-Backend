"""Tests for Phase 3 template-driven XML generation."""

from __future__ import annotations

from pathlib import Path

from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.xml_generator import generate_jats_xml, generate_jats_xml_from_ir

FIXTURE_TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "1458242.xml"

SAMPLE_IR = {
    "front": {
        "title": {
            "type": "title",
            "elements": [{"type": "text", "value": "Generated Paper Title"}],
            "source_block_ids": ["p1_b1"],
        },
        "abstract": {
            "type": "abstract",
            "elements": [{"type": "text", "value": "This is the abstract."}],
            "source_block_ids": ["p1_b2"],
        },
        "keywords": {
            "type": "keywords",
            "elements": [{"type": "text", "value": "sensor, tea"}],
            "source_block_ids": ["p1_b3"],
        },
        "authors": [],
        "affiliations": [],
    },
    "body": {
        "sections": [
            {
                "heading": "INTRODUCTION",
                "heading_element": {
                    "type": "heading",
                    "label": "I.",
                    "elements": [{"type": "text", "value": "INTRODUCTION"}],
                    "source_block_ids": ["p2_b1"],
                },
                "level": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "elements": [{"type": "text", "value": "Intro paragraph."}],
                        "source_block_ids": ["p2_b2"],
                    },
                    {
                        "type": "display_math",
                        "latex": "TAN = fTAN(XTAN)",
                        "label": "(1)",
                        "source_block_ids": ["p6_b43"],
                    },
                ],
                "subsections": [],
                "paragraphs": [],
                "content_source_block_ids": [],
            }
        ],
        "loose_paragraphs": [],
    },
    "back": {
        "references": [
            {
                "type": "reference",
                "elements": [{"type": "text", "value": "[1] Smith et al., 2020."}],
                "source_block_ids": ["p8_b1"],
            }
        ],
        "reference_list": None,
        "other": [],
    },
}


def test_ir_to_semantic_mapping_builds_sections() -> None:
    mapping = ir_to_semantic_mapping(SAMPLE_IR)
    assert mapping.front["title"]["text"] == "Generated Paper Title"
    assert len(mapping.body) == 1
    assert mapping.body[0].semantic_type == "heading"
    assert mapping.body[0].label == "I."
    assert len(mapping.body[0].children) == 2


def test_generate_jats_xml_serializes_quotes_as_hex_entities(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
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
    assert (
        "&#x27;&#x27;Explainable AI&#x27;&#x27; AND &#x27;&#x27;Breast Cancer&#x27;&#x27;" in xml
    )
    assert "&amp;#x27;" not in xml


def test_generate_jats_xml_from_template_and_ir() -> None:
    xml = generate_jats_xml_from_ir(FIXTURE_TEMPLATE, SAMPLE_IR)
    assert xml.startswith("<?xml")
    assert "<article-title>Generated Paper Title</article-title>" in xml
    assert "<label>I.</label>" in xml
    assert "<title>INTRODUCTION</title>" in xml
    assert "Intro paragraph." in xml
    assert "<disp-formula" in xml
    assert "TAN = fTAN(XTAN)" in xml
    assert r"\begin{equation*}" in xml
    assert r"\tag {1}" in xml
    assert "<label>(1)</label>" in xml
    assert "<ref " in xml
    assert "Smith et al." in xml


def test_generate_jats_xml_with_mapping_body() -> None:
    mapping = ir_to_semantic_mapping(SAMPLE_IR)
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert "<kwd>sensor</kwd>" in xml
    assert "<kwd>tea</kwd>" in xml


def test_generate_jats_xml_links_inline_citations_to_ref_list(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
  <back><ref-list><title>References</title></ref-list></back>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="Researchers cited prior work [1] and [2].",
                source_block_ids=["p2_b1"],
            )
        ],
        back={
            "references": [
                {
                    "semantic_type": "reference",
                    "label": "[1]",
                    "text": "[1] A. Author, First paper.",
                    "source_block_ids": ["p8_b1"],
                },
                {
                    "semantic_type": "reference",
                    "label": "[2]",
                    "text": "[2] B. Author, Second paper.",
                    "source_block_ids": ["p8_b2"],
                },
            ]
        },
    )
    xml = generate_jats_xml(template, mapping)
    assert '<xref ref-type="bibr" rid="ref1">[1]</xref>' in xml
    assert '<xref ref-type="bibr" rid="ref2">[2]</xref>' in xml
    assert '<ref id="ref1">' in xml
    assert '<ref id="ref2">' in xml
    assert "First paper" in xml
    assert "<article-title>" in xml
    assert "[1] A. Author" not in xml


def test_generate_jats_xml_creates_back_when_missing(tmp_path: Path) -> None:
    from app.models.semantic_mapping import SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[],
        back={
            "references": [
                {
                    "semantic_type": "reference",
                    "label": "[1]",
                    "text": "[1] A. Author, First paper.",
                    "source_block_ids": ["p8_b1"],
                }
            ]
        },
    )
    xml = generate_jats_xml(template, mapping)
    assert "<back>" in xml
    assert "<ref-list>" in xml
    assert '<ref id="ref1">' in xml


def test_generate_jats_xml_with_illegal_inline_control_char() -> None:
    from app.models.semantic_mapping import MappedInlineElement, MappedSemanticNode, SemanticMappingBody

    mapping = SemanticMappingBody(
        front={
            "title": {
                "semantic_type": "metadata",
                "text": "Title",
                "source_block_ids": ["p1_b1"],
            }
        },
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                source_block_ids=["p4_b1"],
                elements=[MappedInlineElement(type="text", value="bad\x00char\x08here")],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert "badcharhere" in xml
    assert "\x00" not in xml


def test_generate_jats_xml_wraps_abstract_in_bold(tmp_path: Path) -> None:
    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <title-group><article-title>Title</article-title></title-group>
      <abstract><p>Old abstract</p></abstract>
    </article-meta>
  </front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    xml = generate_jats_xml_from_ir(template, SAMPLE_IR)
    assert "<abstract>" in xml
    assert "<p><bold>This is the abstract.</bold></p>" in xml


def test_generate_jats_xml_renders_r_squared_as_superscript(tmp_path: Path) -> None:
    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <title-group><article-title>Title</article-title></title-group>
      <abstract><p>Old abstract</p></abstract>
    </article-meta>
  </front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    ir = {
        **SAMPLE_IR,
        "front": {
            **SAMPLE_IR["front"],
            "abstract": {
                "type": "abstract",
                "elements": [
                    {
                        "type": "text",
                        "value": (
                            "Abstract—The coefficient of determination (R2) of 0.967 "
                            "and the R2 value was high."
                        ),
                    }
                ],
                "source_block_ids": ["p1_b2"],
            },
        },
    }
    xml = generate_jats_xml_from_ir(template, ir)
    assert "<p><bold>Abstract" in xml
    assert "<italic>R</italic><sup>2</sup>" in xml
    assert xml.count("<italic>R</italic><sup>2</sup>") == 2
    assert "<inline-formula>" not in xml


def test_generate_jats_xml_strips_author_name_whitespace(tmp_path: Path) -> None:
    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <title-group><article-title>Title</article-title></title-group>
      <contrib-group>
        <contrib>
          <name-alternatives>
            <string-name>
              <given-names>
 Madhurima 
</given-names>
              <surname>
 Moulick 
</surname>
            </string-name>
          </name-alternatives>
        </contrib>
      </contrib-group>
    </article-meta>
  </front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    xml = generate_jats_xml_from_ir(template, SAMPLE_IR)
    assert "<given-names>Madhurima</given-names>" in xml
    assert "<surname>Moulick</surname>" in xml
    assert "<given-names> Madhurima </given-names>" not in xml
    assert "<surname> Moulick </surname>" not in xml


def test_generate_jats_xml_skips_empty_figure(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(semantic_type="paragraph", text="Intro text.", source_block_ids=["p2_b1"]),
            MappedSemanticNode(semantic_type="figure", source_block_ids=["p2_b2"]),
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert "<fig" not in xml
    assert "Intro text." in xml


def test_generate_jats_xml_renders_display_math_with_deqn_id(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body>
    <sec id="sec1">
      <disp-formula id="deqn1">
        <label>(1)</label>
        <tex-math notation="LaTeX">\\begin{equation*} u = R{s} i \\tag {1}\\end{equation*}</tex-math>
      </disp-formula>
    </sec>
  </body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="display_math",
                latex="u = R{s} i",
                label="(1)",
                source_block_ids=["p3_b1"],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert '<disp-formula id="deqn1">' in xml
    assert r"\begin{equation*}" in xml
    assert "R_{s}" in xml
    assert r"\tag {1}" in xml


def test_generate_jats_xml_renders_inline_math_with_subscripts(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedInlineElement, MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                source_block_ids=["p2_b1"],
                elements=[MappedInlineElement(type="inline_math", latex=r"\chi _{0}")],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert "<inline-formula>" in xml
    assert r"$\chi _{0}$" in xml


def test_generate_jats_xml_renders_figure_with_template_graphic(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body>
    <sec id="sec1">
      <p>Body</p>
      <fig id="fig1">
        <label>Fig. 1.</label>
        <caption><p>Template caption.</p></caption>
        <graphic xlink:href="wang1-3604611.eps"/>
      </fig>
    </sec>
  </body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="Reference frames are shown in Fig. 1.",
                source_block_ids=["p2_b1"],
            ),
            MappedSemanticNode(
                semantic_type="figure",
                label="Fig. 1.",
                source_block_ids=["p2_b2"],
                children=[
                    MappedSemanticNode(
                        semantic_type="caption",
                        text="Reference frames of sensorless controlled SPMSM.",
                        source_block_ids=["p2_b2"],
                    )
                ],
            ),
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert '<fig id="fig1">' in xml
    assert "<label>Fig. 1.</label>" in xml
    assert "Reference frames of sensorless controlled SPMSM." in xml
    assert 'xlink:href="wang1-3604611.eps"' in xml
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in xml


def test_generate_jats_xml_infers_missing_drop_cap_r(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="ESEARCHERS have been seeking alternative instrumen- tal means.",
                source_block_ids=["p2_b1"],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert "<p><bold>R</bold>ESEARCHERS have been seeking alternative instrumental means.</p>" in xml


def test_generate_jats_xml_renders_drop_cap_paragraph(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="paragraph",
                text="RESEARCHERS have been seeking alternative instrumental means.",
                source_block_ids=["p2_b1"],
                metadata={"drop_cap_letter": "R"},
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert "<p><bold>R</bold>ESEARCHERS have been seeking alternative instrumental means.</p>" in xml


def test_generate_jats_xml_nested_sections() -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="section",
                label="I.",
                text="INTRODUCTION",
                children=[
                    MappedSemanticNode(
                        semantic_type="section",
                        label="A.",
                        text="Subsection",
                        children=[
                            MappedSemanticNode(
                                semantic_type="paragraph",
                                text="Nested paragraph.",
                                source_block_ids=["p3_b1"],
                            )
                        ],
                    )
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(FIXTURE_TEMPLATE, mapping)
    assert xml.count("<sec") >= 2
    assert '<sec id="sec1">' in xml
    assert '<sec id="sec1a">' in xml
    assert "<label>A.</label>" in xml
    assert "Nested paragraph." in xml


def test_generate_jats_xml_renders_list_type_attribute(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="list",
                metadata={"list_type": "order"},
                children=[
                    MappedSemanticNode(
                        semantic_type="list_item",
                        label="1)",
                        text="First item.",
                        source_block_ids=["p4_b1"],
                    ),
                    MappedSemanticNode(
                        semantic_type="list_item",
                        label="2)",
                        text="Second item.",
                        source_block_ids=["p4_b2"],
                    ),
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert '<list list-type="ordered">' in xml
    assert 'list_type=' not in xml
    assert "First item." in xml


def test_generate_jats_xml_avoids_duplicate_intro_section_wrapper(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="heading",
                label="I.",
                text="INTRODUCTION",
                children=[
                    MappedSemanticNode(
                        semantic_type="heading",
                        label="I.",
                        text="INTRODUCTION",
                        children=[
                            MappedSemanticNode(
                                semantic_type="paragraph",
                                text="Intro paragraph.",
                                source_block_ids=["p2_b1"],
                            )
                        ],
                    )
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert '<sec id="sec1">' in xml
    assert '<label>I.</label>' in xml
    assert "<title>INTRODUCTION</title>" in xml
    assert "Intro paragraph." in xml
    assert 'id="sec1 I"' not in xml
    assert xml.count('<sec id="sec1">') == 1


def test_generate_jats_xml_nested_roman_section_not_sec11(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="heading",
                label="I.",
                text="INTRODUCTION",
                children=[
                    MappedSemanticNode(
                        semantic_type="heading",
                        label="II.",
                        text="MATERIALS AND METHODOLOGY",
                        children=[
                            MappedSemanticNode(
                                semantic_type="subsection",
                                label="A.",
                                text="Chemical Reagents and Standards",
                                children=[
                                    MappedSemanticNode(
                                        semantic_type="paragraph",
                                        text="Pure graphite was obtained.",
                                        source_block_ids=["p3_b1"],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert 'id="sec11"' not in xml
    assert '<sec id="sec2">' in xml
    assert '<sec id="sec2a">' in xml


def test_generate_jats_xml_nested_subsection_ids_under_roman_section(tmp_path: Path) -> None:
    from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody

    template = tmp_path / "template.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front><article-meta><title-group><article-title>Title</article-title></title-group></article-meta></front>
  <body><sec id="sec1"><p>Body</p></sec></body>
</article>
""",
        encoding="utf-8",
    )
    mapping = SemanticMappingBody(
        front={},
        body=[
            MappedSemanticNode(
                semantic_type="heading",
                label="II.",
                text="MATERIALS AND METHODOLOGY",
                children=[
                    MappedSemanticNode(
                        semantic_type="subsection",
                        label="A.",
                        text="Chemical Reagents and Standards",
                        children=[
                            MappedSemanticNode(
                                semantic_type="paragraph",
                                text="Pure graphite was obtained.",
                                source_block_ids=["p3_b1"],
                            )
                        ],
                    ),
                    MappedSemanticNode(
                        semantic_type="subsection",
                        label="B.",
                        text="Equipment Specifications",
                        children=[
                            MappedSemanticNode(
                                semantic_type="paragraph",
                                text="PGSTAT101 potentiostat system.",
                                source_block_ids=["p3_b2"],
                            )
                        ],
                    ),
                ],
            )
        ],
        back={},
    )
    xml = generate_jats_xml(template, mapping)
    assert '<sec id="sec2">' in xml
    assert '<sec id="sec2a">' in xml
    assert '<sec id="sec2b">' in xml
    assert "Pure graphite was obtained." in xml
    assert "PGSTAT101 potentiostat system." in xml
