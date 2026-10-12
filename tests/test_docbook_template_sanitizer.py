"""Strip foreign sample-book content from DocBook templates."""

from __future__ import annotations

from lxml import etree

from app.services.docbook_generator import generate_docbook_book_xml
from app.services.docbook_metadata_overlay import apply_pdf_metadata_to_docbook_book
from app.services.docbook_template_sanitizer import sanitize_docbook_template_after_pdf_overlay
from app.services.source_identity import SourceIdentityRecord
from app.services.template_format import DOCBOOK_NS
from app.models.semantic_mapping import MappedSemanticNode, SemanticMappingBody


def test_sanitize_removes_gottlieb_marketing_and_front_matter() -> None:
    root = etree.fromstring(
        f"""<book xmlns="http://docbook.org/ns/docbook" xml:id="b-9798216512332">
      <info>
        <title>Political and Spiritual</title>
        <cover role="halfTitle">
          <para>Praise for <emphasis>Political and Spiritual</emphasis></para>
          <para>—John B. Cobb Jr.</para>
        </cover>
        <cover role="series"><para>Other books by Roger S. Gottlieb</para></cover>
        <abstract role="blurb"><para>Roger S. Gottlieb is internationally known</para></abstract>
        <keywordset><keyword>religion and politics</keyword></keywordset>
        <legalnotice><para>Library of Congress Control Number: 2014952284</para></legalnotice>
        <biblioid class="other" otherclass="schemaVersion">1</biblioid>
        <revhistory><revision><date>2014</date></revision></revhistory>
      </info>
      <colophon><para>ANSI/NISO Z39.48-1992</para></colophon>
      <part role="front">
        <preface role="prelims">
          <info><title>Title Pages</title></info>
          <mediaobject><imageobject>
            <imagedata fileref="pdfs/9798216512332.0001.pdf"/>
          </imageobject></mediaobject>
        </preface>
        <dedication><para>Earth&#x2019;s the right place for love</para></dedication>
        <toc><info><title>Contents</title></info></toc>
      </part>
      <chapter><title>Old chapter</title><para>Template body.</para></chapter>
    </book>""".encode("utf-8")
    )
    source = SourceIdentityRecord(
        extraction_id="moss",
        source_pdf_sha256="sha",
        source_filename="9781498547703.pdf",
        title="Political Poetry in the Wake of the Second Spanish Republic",
        subtitle="Rafael Alberti, Pablo Neruda, and Nicolás Guillén",
        authors=["Grant D. Moss"],
        publisher="Lexington Books",
        publication_year=2018,
        isbn="978-1-4985-4770-3",
        isbns=["978-1-4985-4770-3", "978-1-4985-4771-0"],
    )
    apply_pdf_metadata_to_docbook_book(root, source)
    sanitize_docbook_template_after_pdf_overlay(root, source)
    xml = etree.tostring(root, encoding="unicode")
    assert "Roger S. Gottlieb" not in xml
    assert "Political and Spiritual" not in xml
    assert "Political Poetry in the Wake of the Second Spanish Republic" in xml
    assert "John B. Cobb" not in xml
    assert "2014952284" not in xml
    assert "9798216512332" not in xml
    assert "Earth" not in xml or "right place for love" not in xml
    assert root.find(f"{{{DOCBOOK_NS}}}part") is None
    assert root.find(f"{{{DOCBOOK_NS}}}colophon") is None
    assert root.find(f"{{{DOCBOOK_NS}}}chapter") is None


def test_generate_docbook_uses_pdf_body_not_template_chapter(tmp_path) -> None:
    template = tmp_path / "t.xml"
    template.write_text(
        f"""<book xmlns="http://docbook.org/ns/docbook">
      <info><title>Wrong Template Title</title>
        <cover role="halfTitle"><para>Praise for Political and Spiritual</para></cover>
      </info>
      <chapter><title>Template</title><para>Template-only paragraph.</para></chapter>
    </book>""",
        encoding="utf-8",
    )
    source = SourceIdentityRecord(
        extraction_id="x",
        source_pdf_sha256="sha",
        source_filename="moss.pdf",
        title="Political Poetry in the Wake of the Second Spanish Republic",
        authors=["Grant D. Moss"],
        isbn="978-1-4985-4770-3",
        publication_year=2018,
    )
    mapping = SemanticMappingBody(
        body=[
            MappedSemanticNode(
                semantic_type="heading",
                text="Intellectuals and the Second Spanish Republic",
                metadata={"level": 1},
                children=[
                    MappedSemanticNode(
                        semantic_type="paragraph",
                        text="Unique Moss PDF body marker xyzzy-moss-99881.",
                    )
                ],
            )
        ]
    )
    xml, _ = generate_docbook_book_xml(template, source=source, mapping=mapping)
    assert "Political and Spiritual" not in xml
    assert "Template-only paragraph" not in xml
    assert "xyzzy-moss-99881" in xml
    assert "Intellectuals and the Second Spanish Republic" in xml
