"""ref-count must match <ref-list> length after JATS generation."""

from __future__ import annotations

from lxml import etree

from app.services.xml_generator import _apply_back_matter, _sync_ref_count_to_ref_list


def test_apply_back_matter_preserves_template_refs_when_mapping_empty() -> None:
    article = etree.fromstring(
        b"""<article>
  <back><ref-list>
    <ref id="ref1"><label>[1]</label></ref>
    <ref id="ref2"><label>[2]</label></ref>
  </ref-list></back>
</article>"""
    )
    written = _apply_back_matter(article, {"references": []})
    assert written is None
    assert len(article.xpath("//*[local-name()='ref-list']/*[local-name()='ref']")) == 2


def test_sync_ref_count_uses_explicit_written_count() -> None:
    article = etree.fromstring(
        b"""<article>
  <front><article-meta><counts><ref-count count="29"/></counts></article-meta></front>
  <back><ref-list><title>References</title></ref-list></back>
</article>"""
    )
    back = {
        "references": [
            {"semantic_type": "reference", "label": f"[{index}]", "text": f"Ref {index}."}
            for index in range(1, 33)
        ]
    }
    written = _apply_back_matter(article, back)
    assert written == 32
    _sync_ref_count_to_ref_list(article, reference_count=written)
    assert (
        article.xpath("string(//*[local-name()='ref-count']/@count)")
        == "32"
    )
    assert len(article.xpath("//*[local-name()='ref-list']/*[local-name()='ref']")) == 32
