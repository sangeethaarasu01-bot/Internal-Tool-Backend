"""Smoke test for periodicals.dtd fixture (validator.py will use the real DTD later)."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
DTD_PATH = ROOT / "tests" / "fixtures" / "periodicals.dtd"


def test_periodicals_dtd_loads_without_error() -> None:
    assert DTD_PATH.exists(), "periodicals.dtd fixture missing"
    dtd = etree.DTD(str(DTD_PATH))
    assert dtd is not None


def test_minimal_article_validates_against_placeholder_dtd() -> None:
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
