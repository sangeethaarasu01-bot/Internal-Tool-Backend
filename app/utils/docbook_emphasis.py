"""Map IR inline text styles to DocBook 5.0 <emphasis> inside paragraphs."""

from __future__ import annotations

from typing import Sequence

from lxml import etree

from app.models.ir_schema import IRInlineMathElement, IRTextElement
from app.services.template_format import DOCBOOK_NS
from app.utils.book_text_typography import prepare_book_text_for_xml


def _append_text(parent: etree._Element, text: str, last: etree._Element | None) -> etree._Element | None:
    if not text:
        return last
    if last is None:
        parent.text = (parent.text or "") + text
        return last
    last.tail = (last.tail or "") + text
    return last


def append_docbook_emphasis_inline(
    parent: etree._Element,
    elements: Sequence[IRTextElement | IRInlineMathElement],
) -> None:
    """Append styled inline content under a DocBook ``<para>`` (or similar)."""
    emphasis_ns = f"{{{DOCBOOK_NS}}}emphasis"
    last: etree._Element | None = None
    for item in elements:
        if isinstance(item, IRInlineMathElement):
            continue
        if not isinstance(item, IRTextElement):
            continue
        text = prepare_book_text_for_xml(item.value or "")
        if not text:
            continue
        if not (item.bold or item.italic or item.superscript or item.subscript):
            last = _append_text(parent, text, last)
            continue
        host: etree._Element = parent
        styled_leaf: etree._Element | None = None
        if item.bold:
            bold_el = etree.SubElement(parent, emphasis_ns)
            bold_el.set("role", "bold")
            host = bold_el
            styled_leaf = bold_el
        if item.italic:
            italic_el = etree.SubElement(host, emphasis_ns)
            italic_el.set("role", "italic")
            styled_leaf = italic_el
        if item.superscript:
            sup = etree.SubElement(host if styled_leaf is None else styled_leaf, f"{{{DOCBOOK_NS}}}superscript")
            sup.text = text
            last = sup
            continue
        if item.subscript:
            sub = etree.SubElement(host if styled_leaf is None else styled_leaf, f"{{{DOCBOOK_NS}}}subscript")
            sub.text = text
            last = sub
            continue
        if styled_leaf is None:
            last = _append_text(parent, text, last)
        else:
            styled_leaf.text = (styled_leaf.text or "") + text
            last = styled_leaf
