from pathlib import Path

from lxml import etree

from app.services.xml_validation_report import validate_generated_xml

DTD_PATH = Path(__file__).resolve().parent / "fixtures" / "periodicals.dtd"


def test_well_formed_xml_passes() -> None:
    xml = "<article><body><p>ok</p></body></article>"
    report = validate_generated_xml(xml)
    assert report.well_formed
    assert not report.errors


def test_invalid_xml_fails() -> None:
    report = validate_generated_xml("<article><unclosed>")
    assert not report.well_formed
    assert report.errors


def test_dtd_validation_on_fixture_article() -> None:
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
          <title-group><article-title>Sample</article-title></title-group>
          <contrib-group>
            <contrib contrib-type="author">
              <name-alternatives><string-name><surname>Doe</surname></string-name></name-alternatives>
            </contrib>
          </contrib-group>
          <abstract><p>Abstract.</p></abstract>
        </article-meta>
      </front>
      <body><sec id="s1"><title>Intro</title><p>Text.</p></sec></body>
      <back><ref-list><ref id="r1"><mixed-citation>Ref.</mixed-citation></ref></ref-list></back>
    </article>
    """
    report = validate_generated_xml(xml.decode(), dtd_path=DTD_PATH)
    assert report.well_formed
    assert report.dtd_validated
    assert report.dtd_passed is True
