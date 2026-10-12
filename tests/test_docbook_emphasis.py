from __future__ import annotations

from lxml import etree

from app.models.ir_schema import IRTextElement
from app.services.template_format import DOCBOOK_NS
from app.utils.docbook_emphasis import append_docbook_emphasis_inline


def test_personblurb_bold_and_italic_emphasis() -> None:
    para = etree.Element(f"{{{DOCBOOK_NS}}}para")
    append_docbook_emphasis_inline(
        para,
        [
            IRTextElement(value="Grant D. Moss", bold=True),
            IRTextElement(value=" is an Associate Professor at "),
            IRTextElement(value="La Universidad de Salamanca", italic=True),
            IRTextElement(value="."),
        ],
    )
    xml = etree.tostring(para, encoding="unicode")
    assert 'role="bold"' in xml and "Grant D. Moss" in xml
    assert 'role="italic"' in xml and "La Universidad de Salamanca" in xml
