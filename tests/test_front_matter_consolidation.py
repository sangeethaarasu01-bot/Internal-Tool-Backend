"""Front matter consolidation and IR repair (idempotent)."""

from app.models.ir_schema import IRNode
from app.models.semantic_document import SemanticBody, SemanticDocument, SemanticFrontMatter
from app.pipeline.phase1.ir_text import ir_node_plain_text
from app.services.front_matter_consolidation import consolidate_semantic_front_matter, repair_ir_front_matter
from app.services.ir_builder import build_abstract, build_paragraph
from app.services.layout.semantic_builder import _element
from app.utils.front_matter_recovery import strip_abstract_label


def _paragraph_ir(text: str) -> IRNode:
    return build_paragraph(text)


def test_strip_abstract_label() -> None:
    assert strip_abstract_label("Abstract— The rapid adoption").startswith("The rapid")


def test_consolidate_multiline_abstract_from_loose_paragraphs() -> None:
    front = SemanticFrontMatter()
    front.abstract = build_abstract("Abstract— The rapid adoption of electric vehicles (EVs) has")
    body = SemanticBody(
        loose_paragraphs=[
            _paragraph_ir(
                "spurred demand for accurate battery health estimation across fleets."
            ),
            _paragraph_ir("Index Terms— Electric vehicle, battery state of health"),
        ]
    )
    document = SemanticDocument(front=front, body=body)
    consolidate_semantic_front_matter(document)
    abstract_text = ir_node_plain_text(document.front.abstract)
    assert "spurred demand" in abstract_text
    assert "Index Terms" not in abstract_text
    assert len(document.body.loose_paragraphs) == 0


def test_consolidate_drops_running_header_and_duplicate_title() -> None:
    title = "Split Multi-Task Federated Learning for Battery Health"
    front = SemanticFrontMatter(title=_element("TITLE", title, [], 0.9))
    body = SemanticBody(
        loose_paragraphs=[
            _paragraph_ir("IEEE TRANSACTIONS ON CONSUMER ELECTRONICS 1"),
            _paragraph_ir(title),
            _paragraph_ir("I. INTRODUCTION"),
        ]
    )
    document = SemanticDocument(front=front, body=body)
    consolidate_semantic_front_matter(document)
    assert len(document.body.loose_paragraphs) == 1
    assert "INTRODUCTION" in ir_node_plain_text(document.body.loose_paragraphs[0])


def test_repair_ir_front_matter_idempotent() -> None:
    ir = {
        "front": {
            "abstract": build_abstract("Abstract— First line only.").to_json_dict(),
        },
        "body": {
            "sections": [],
            "loose_paragraphs": [
                build_paragraph("Second abstract sentence with enough length to qualify.").to_json_dict(),
                build_paragraph("IEEE TRANSACTIONS ON CONSUMER ELECTRONICS 2").to_json_dict(),
            ],
        },
        "back": {"references": []},
    }
    repair_ir_front_matter(ir)
    first_abs = ir["front"]["abstract"]
    first_text = _node_text_from_ir(first_abs)
    repair_ir_front_matter(ir)
    second_text = _node_text_from_ir(ir["front"]["abstract"])
    assert first_text == second_text
    assert "Second abstract" in second_text
    assert len(ir["body"]["loose_paragraphs"]) == 0


def _node_text_from_ir(node: dict) -> str:
    from app.services.ir_semantic_adapter import _node_text

    return _node_text(node) or ""


def test_keywords_wrapped_line_merged_from_loose() -> None:
    front = SemanticFrontMatter()
    front.keywords = _element(
        "KEYWORDS",
        "Index Terms— Electric vehicle, battery state of health",
        [],
        0.9,
        keywords=["Electric vehicle", "battery state of health"],
    )
    body = SemanticBody(
        loose_paragraphs=[
            _paragraph_ir("state of charge (SOC), battery management system (BMS)."),
        ]
    )
    document = SemanticDocument(front=front, body=body)
    consolidate_semantic_front_matter(document)
    kw_text = ir_node_plain_text(document.front.keywords)
    assert "state of charge" in kw_text.lower()
    assert len(document.body.loose_paragraphs) == 0
