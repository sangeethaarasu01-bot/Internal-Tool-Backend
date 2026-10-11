"""XML-level relocation of misplaced proof-PDF front matter."""

from lxml import etree

from app.services.xml_generator import relocate_misplaced_front_matter

TITLE = (
    "Split Multi-Task Federated Learning for Battery Health and "
    "Capacity Estimation in Electric Vehicles"
)


def test_relocate_moves_title_abstract_and_keywords_from_loose_body_paras() -> None:
    article = etree.fromstring(
        f"""<article>
  <front><article-meta>
    <title-group><article-title></article-title></title-group>
    <abstract><p><bold>Abstract— The rapid adoption of electric vehicles (EVs) has</bold></p></abstract>
    <kwd-group kwd-group-type="AuthorFree">
      <kwd>Index Terms— Electric vehicle</kwd>
      <kwd>battery state of health</kwd>
    </kwd-group>
  </article-meta></front>
  <body>
    <sec id="sec5"><title>V. CONCLUSION</title><p>Done.</p></sec>
    <p>IEEE TRANSACTIONS ON CONSUMER ELECTRONICS 1</p>
    <p>{TITLE}</p>
    <p>heightened the need for advanced diagnostic frameworks to ensure safety across large fleets with many technical details about federated learning pipelines and transformer models used in the study for electric vehicle battery management systems.</p>
    <p>Machine learning has emerged as a promising approach for battery diagnostics under diverse real-world operating conditions with strong generalization across heterogeneous vehicle fleets.</p>
    <p>range, lifespan, and overall efficiency, state of charge (SOC), battery management system (BMS), split federated learning, transformer.</p>
  </body>
</article>"""
    )

    relocate_misplaced_front_matter(article)
    relocate_misplaced_front_matter(article)

    title = article.xpath("string(//*[local-name()='article-title'])").strip()
    assert TITLE in title

    abstract = article.xpath("string(//*[local-name()='abstract']//*[local-name()='p'])")
    assert "heightened the need" in abstract
    assert "Machine learning has emerged" in abstract
    assert "range, lifespan" not in abstract
    assert len(abstract) > 200

    kwds = article.xpath("//*[local-name()='kwd']/text()")
    assert len(kwds) >= 4
    assert any("state of charge" in (k or "").lower() for k in kwds)
    assert any("range" in (k or "").lower() or "lifespan" in (k or "").lower() for k in kwds)

    loose = article.xpath("count(/*[local-name()='body']/*[local-name()='p'])")
    assert loose == 0
