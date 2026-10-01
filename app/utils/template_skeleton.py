"""Separate IEEE/JATS template STRUCTURE from example DOCUMENT content.

The sample XML defines hierarchy, tags, attributes, and ordering. Example text
nodes (titles, paragraphs, sample authors, etc.) must not appear in final output.
"""

from __future__ import annotations

from lxml import etree

from app.utils.xml_helpers import is_element_node, parse_xml_string, xml_local_name

# journal-meta is usually vendor/journal scaffolding — keep its text nodes.
_PRESERVE_TEXT_SUBTREE_LOCAL = frozenset({"journal-meta", "processing-meta"})


def clear_subtree_text(elem: etree._Element) -> None:
    """Remove all text/tail under elem (attributes unchanged)."""
    elem.text = None
    for child in elem:
        clear_subtree_text(child)
        child.tail = None


def _find_by_local_tag(root: etree._Element, tag: str) -> list[etree._Element]:
    return root.xpath(f".//*[local-name()='{tag}']")


def strip_article_meta_example_content(root: etree._Element) -> None:
    for am in _find_by_local_tag(root, "article-meta"):
        clear_subtree_text(am)


def _clear_prose_element(elem: etree._Element) -> None:
    """Remove example text from a prose element; keep the element shell."""
    elem.text = None
    for child in list(elem):
        if is_element_node(child):
            elem.remove(child)


def strip_body_document_text(root: etree._Element) -> None:
    """Clear sample article text in body but keep sec/fig/table/formula hierarchy."""
    prose_tags = frozenset({"p", "title", "label", "article-title", "ack", "fn", "td", "th"})
    for body in _find_by_local_tag(root, "body"):
        for el in body.iter():
            if not is_element_node(el):
                continue
            local = xml_local_name(el)
            if local in prose_tags:
                _clear_prose_element(el)
            elif local == "caption":
                for title in el.xpath(".//*[local-name()='title']"):
                    _clear_prose_element(title)


def strip_body_example_content(root: etree._Element) -> None:
    """Legacy: remove all body children (prefer strip_body_document_text)."""
    for body in _find_by_local_tag(root, "body"):
        for child in list(body):
            if is_element_node(child):
                body.remove(child)


def strip_back_example_content(root: etree._Element) -> None:
    for back in _find_by_local_tag(root, "back"):
        for ref_list in _find_by_local_tag(back, "ref-list"):
            for child in list(ref_list):
                if is_element_node(child) and xml_local_name(child) == "ref":
                    ref_list.remove(child)
        for bio in _find_by_local_tag(back, "bio"):
            clear_subtree_text(bio)
        for ack in _find_by_local_tag(back, "ack"):
            clear_subtree_text(ack)
        for fn_group in _find_by_local_tag(back, "fn-group"):
            clear_subtree_text(fn_group)


def prepare_template_for_pdf_content(root: etree._Element) -> None:
    """Clear example document text while preserving template structure and journal-meta."""
    strip_article_meta_example_content(root)
    strip_body_document_text(root)
    strip_back_example_content(root)


def skeleton_template_xml(template_xml: str) -> str:
    """Return structural template XML with example article/body/back text removed."""
    root = parse_xml_string(template_xml)
    prepare_template_for_pdf_content(root)
    return etree.tostring(root, encoding="unicode")


def collect_example_text_snippets(root: etree._Element, limit: int = 12) -> list[str]:
    """Debug helper: short non-empty text nodes under article-meta/body/back."""
    snippets: list[str] = []
    for region in ("article-meta", "body", "back"):
        for node in _find_by_local_tag(root, region):
            for el in node.iter():
                if not is_element_node(el):
                    continue
                if xml_local_name(el) in _PRESERVE_TEXT_SUBTREE_LOCAL:
                    continue
                text = (el.text or "").strip()
                if len(text) >= 8 and text not in snippets:
                    snippets.append(text[:120])
                if len(snippets) >= limit:
                    return snippets
    return snippets
