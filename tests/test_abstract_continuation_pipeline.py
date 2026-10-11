"""Abstract continuation across columns / after Index Terms."""

from __future__ import annotations

from app.models.semantic_document import SemanticBackMatter, SemanticBody, SemanticDocument, SemanticFrontMatter
from app.pipeline.phase1.ir_text import ir_node_plain_text
from app.services.front_matter_consolidation import consolidate_semantic_front_matter
from app.services.ir_builder import build_abstract, build_paragraph
from app.services.xml_generator import (
    _is_relocate_abstract_fragment,
    _join_relocate_abstract_parts,
    relocate_misplaced_front_matter,
)
from app.services.front_matter_consolidation import repair_ir_front_matter
from app.services.ir_builder import build_abstract as ir_build_abstract
from app.utils.front_matter_recovery import (
    is_keywords_continuation,
    is_post_keywords_abstract_fragment,
    merge_abstract_segment,
)
from app.utils.text_utils import merge_block_texts
from lxml import etree


def test_merge_abstract_segment_inserts_percent_before_state_of_the_art() -> None:
    broken = (
        "corresponding to a relative error of approximately state-of-the-art approaches."
    )
    fixed = merge_abstract_segment(
        broken,
        "1.80%, significantly outperforming ",
    )
    assert "approximately 1.80%" in fixed
    assert "significantly outperforming" in fixed
    assert "state-of-the-art" in fixed


def test_merge_block_texts_keeps_space_before_stopwords() -> None:
    assert merge_block_texts(["heightened", "the need for advanced"]) == "heightened the need for advanced"
    assert merge_block_texts(["diagnostic", "frameworks to ensure"]) == "diagnostic frameworks to ensure"
    assert merge_block_texts(["dual", "challenges of battery health"]) == "dual challenges of battery health"
    assert merge_block_texts(["split", "learning with the collaborative"]) == "split learning with the collaborative"
    assert merge_block_texts(["share", "partial model updates"]) == "share partial model updates"
    assert merge_block_texts(["instru", "ments like electronic"]) == "instruments like electronic"
    assert "state-of-the-art" in merge_block_texts(
        ["state-of-the-art", "approaches for deployment"]
    )


def test_keywords_continuation_rejects_abstract_tail_fragments() -> None:
    assert not is_keywords_continuation("1.80%, significantly outperforming ")
    assert not is_keywords_continuation("in real-world EV systems.")
    assert is_keywords_continuation("state of charge, federated learning,")


def test_post_keywords_abstract_fragment_detects_percent_tail() -> None:
    tail = "1.80%, significantly outperforming state-of-the-art approaches."
    short = "1.80%, significantly outperforming "
    assert is_post_keywords_abstract_fragment(tail)
    assert is_post_keywords_abstract_fragment(short)
    assert not is_post_keywords_abstract_fragment("Index Terms— battery, SOC")


def test_consolidate_absorbs_abstract_after_index_terms() -> None:
    front = SemanticFrontMatter()
    front.abstract = build_abstract(
        "Abstract—The rapid adoption of electric vehicles (EVs) has heightened the need "
        "for advanced diagnostic frameworks, corresponding to a relative error of approximately "
    )
    front.keywords = None
    body = SemanticBody()
    body.loose_paragraphs = [
        build_paragraph(
            "Index Terms— Electric vehicle, battery state of health, federated learning."
        ),
        build_paragraph("1.80%, significantly outperforming state-of-the-art approaches."),
        build_paragraph(
            "By training a single model for both tasks and performing computations during "
            "charging sessions, the framework minimizes energy consumption."
        ),
        build_paragraph("in real-world EV systems."),
    ]
    document = SemanticDocument(front=front, body=body, back=SemanticBackMatter(), unknown=[])
    consolidate_semantic_front_matter(document)

    abstract_text = ir_node_plain_text(document.front.abstract)
    assert "1.80%" in abstract_text
    assert "significantly outperforming" in abstract_text
    assert "state-of-the-art" in abstract_text
    assert "charging sessions" in abstract_text
    assert "in real-world EV systems" in abstract_text
    assert "Index Terms" not in abstract_text
    assert len(document.body.loose_paragraphs) == 0


def test_relocate_joins_short_percent_abstract_fragment() -> None:
    parts = [
        "Abstract— The rapid adoption ends at approximately ",
        "1.80%, significantly outperforming state-of-the-art approaches.",
    ]
    merged = _join_relocate_abstract_parts(parts)
    assert "1.80%" in merged
    assert "state-of-the-art" in merged
    assert _is_relocate_abstract_fragment("1.80%, significantly outperforming ")


def test_relocate_xml_appends_closing_real_world_fragment() -> None:
    article = etree.fromstring(
        """<article>
  <front><article-meta>
    <abstract><p>Abstract— ensuring practicality for large-scale deployment</p></abstract>
    <kwd-group><kwd>Index Terms— SOC</kwd></kwd-group>
  </article-meta></front>
  <body>
    <p>in real-world EV systems.</p>
  </body>
</article>"""
    )
    relocate_misplaced_front_matter(article)
    abstract = article.xpath("string(//*[local-name()='abstract']//*[local-name()='p'])")
    assert "large-scale deployment" in abstract
    assert "real-world EV systems" in abstract
    assert article.xpath("count(/*[local-name()='body']/*[local-name()='p'])") == 0


def test_relocate_xml_preserves_percent_in_abstract() -> None:
    article = etree.fromstring(
        """<article>
  <front><article-meta>
    <abstract><p><bold>Abstract— Ends at approximately </bold></p></abstract>
    <kwd-group><kwd>Index Terms— SOC</kwd></kwd-group>
  </article-meta></front>
  <body>
    <p>1.80%, significantly outperforming state-of-the-art approaches.</p>
    <p>By training a single model for both tasks the framework minimizes overhead.</p>
  </body>
</article>"""
    )
    relocate_misplaced_front_matter(article)
    abstract = article.xpath("string(//*[local-name()='abstract']//*[local-name()='p'])")
    assert "1.80%" in abstract
    assert "state-of-the-art" in abstract
    assert "&amp;" not in abstract or "%" in abstract


def test_relocate_xml_fixes_approximately_gap_with_short_percent_para() -> None:
    article = etree.fromstring(
        """<article>
  <front><article-meta>
    <abstract><p>Abstract— error of approximately state-of-the-art approaches.</p></abstract>
    <kwd-group><kwd>Index Terms— EV</kwd></kwd-group>
  </article-meta></front>
  <body>
    <p>1.80%, significantly outperforming </p>
  </body>
</article>"""
    )
    relocate_misplaced_front_matter(article)
    abstract = article.xpath("string(//*[local-name()='abstract']//*[local-name()='p'])")
    assert "1.80%" in abstract
    assert "significantly outperforming" in abstract
    assert "approximately 1.80%" in abstract.replace("  ", " ")


def test_reconcile_rebuilds_two_column_abstract_in_reading_order() -> None:
    """Rebuild from blocks; never inject tail fragments after 'This paper presents'."""
    from app.models.document_structure import ProcessedBlock
    from app.utils.front_matter_recovery import recover_abstract_tail_from_unmapped_blocks

    def _pb(
        bid: str,
        order: int,
        text: str,
        *,
        column: str = "LEFT",
        classification: str = "PARAGRAPH",
    ) -> ProcessedBlock:
        return ProcessedBlock(
            block_id=bid,
            page_number=1,
            reading_order_index=order,
            column=column,
            classification=classification,
            confidence=0.9,
            bbox=[50.0, 100.0, 300.0, 112.0],
            text=text,
            block_type="text",
        )

    front = SemanticFrontMatter()
    front.abstract = build_abstract(
        "Abstract— broken approximately state-of-the-art approaches. deployment",
        source_block_ids=["p1_b9"],
        page_numbers=[1],
    )
    processed = [
        _pb("p1_b9", 8, "Abstract—The rapid adoption of ", classification="ABSTRACT"),
        _pb("p1_b25", 24, "privacy-preserving solutions. This "),
        _pb("p1_b26", 25, "paper presents a Split Multi-Task "),
        _pb("p1_b45", 44, "to a relative error of approximately ", column="RIGHT"),
        _pb("p1_b46", 45, "1.80%, significantly outperforming ", column="RIGHT"),
        _pb("p1_b47", 46, "state-of-the-art approaches. ", column="RIGHT"),
        _pb("p1_b53", 52, "practicality for large-scale deployment ", column="RIGHT"),
        _pb("p1_b54", 53, "in real-world EV systems.", column="RIGHT"),
        _pb("p1_b57", 56, "I. INTRODUCTION", column="RIGHT", classification="SECTION"),
    ]
    recover_abstract_tail_from_unmapped_blocks(front, processed, set())
    abstract_text = ir_node_plain_text(front.abstract)
    assert abstract_text.startswith("The rapid adoption of")
    assert "This 1.80" not in abstract_text
    assert "paper presents" in abstract_text
    normalized = abstract_text.replace("  ", " ")
    assert "approximately 1.80%, significantly outperforming state-of-the-art" in normalized
    assert normalized.rstrip().endswith("in real-world EV systems.")


def test_repair_ir_recovers_tail_from_stored_blocks() -> None:
    from app.models.document_structure import ProcessedBlock

    abstract_node = ir_build_abstract(
        "Abstract— corresponding to a relative error of approximately ",
        source_block_ids=["p1_b10"],
        page_numbers=[1],
    ).to_json_dict()
    ir = {
        "front": {
            "abstract": abstract_node,
            "keywords": {
                "type": "KEYWORDS",
                "text": "Index Terms— federated learning.",
                "source_block_ids": ["p1_b40"],
                "page_numbers": [1],
                "confidence": 0.9,
                "elements": [],
                "children": [],
            },
        },
        "body": {"loose_paragraphs": []},
    }
    def _pb(block_id: str, order: int, text: str, classification: str = "PARAGRAPH") -> ProcessedBlock:
        return ProcessedBlock(
            block_id=block_id,
            page_number=1,
            reading_order_index=order,
            column="LEFT",
            classification=classification,
            confidence=0.9,
            bbox=[50.0, 100.0, 300.0, 112.0],
            text=text,
            block_type="text",
        )

    blocks = [
        _pb("p1_b40", 40, "Index Terms— federated learning.", "KEYWORDS"),
        _pb("p1_b46", 46, "1.80%, significantly outperforming "),
        _pb("p1_b54", 54, "in real-world EV systems."),
    ]
    repair_ir_front_matter(ir, processed_blocks=blocks)
    from app.services.front_matter_consolidation import _node_plain

    abstract_text = _node_plain(ir["front"]["abstract"])
    assert "1.80%" in abstract_text
    assert "significantly outperforming" in abstract_text
    assert "real-world EV systems" in abstract_text
