"""Layout pipeline → PaperData adapter."""

from app.agent.layout_paper_adapter import semantic_document_to_paper
from app.models.ir_schema import IRNode, IRTextElement
from app.models.semantic_document import SemanticBody, SemanticDocument, SemanticFrontMatter, SemanticSection


def _text_node(value: str, node_type: str = "paragraph") -> IRNode:
    return IRNode(type=node_type, elements=[IRTextElement(value=value)])


def test_semantic_document_to_paper_uses_ir_text_not_template() -> None:
    doc = SemanticDocument(
        front=SemanticFrontMatter(
            title=_text_node("PDF Paper Title", "title"),
            abstract=_text_node("Abstract text from the PDF document.", "abstract"),
            authors=[_text_node("Jane Q. Author", "AUTHOR")],
        ),
        body=SemanticBody(
            sections=[
                SemanticSection(
                    heading="I. INTRODUCTION",
                    heading_element=_text_node("I. INTRODUCTION", "heading"),
                    level=1,
                    paragraphs=[_text_node("First paragraph exactly from PDF.", "paragraph")],
                )
            ]
        ),
    )
    paper = semantic_document_to_paper(doc)
    assert paper.title == "PDF Paper Title"
    assert "Abstract text from the PDF" in paper.abstract
    assert paper.authors and paper.authors[0].full_name == "Jane Q. Author"
    assert paper.sections[0].title
    assert "First paragraph exactly from PDF" in paper.sections[0].paragraphs[0]
