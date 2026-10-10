"""Remove empty placeholder elements from generated JATS XML."""

from __future__ import annotations

from lxml import etree

from app.utils.xml_helpers import is_element_node, xml_local_name

_PRUNE_WHEN_EMPTY = frozenset(
    {
        "author-comment",
        "xplore-article-id",
        "xplore-issue",
        "xplore-pub-id",
        "funding-source",
        "award-id",
        "funding-statement",
        "award-group",
        "funding-group",
    }
)

_KEEP_STRUCTURE = frozenset(
    {
        "article",
        "front",
        "back",
        "body",
        "article-meta",
        "journal-meta",
        "contrib-group",
        "counts",
        "ref-list",
        "title-group",
        "journal-title-group",
        "publisher",
        "history",
        "pub-date",
        "abstract",
        "kwd-group",
    }
)


def _element_has_content(element: etree._Element) -> bool:
    if (element.text or "").strip():
        return True
    for child in element:
        if not is_element_node(child):
            continue
        if _element_has_content(child):
            return True
    if element.tail and element.tail.strip():
        return True
    return False


def _prune_aff_if_empty(article_meta: etree._Element) -> None:
    for aff in list(article_meta.findall("aff")):
        if not _element_has_content(aff):
            article_meta.remove(aff)


def _prune_ack_shell(back: etree._Element) -> None:
    for ack in list(back.findall("ack")):
        for title in list(ack.findall("title")):
            if not _element_has_content(title):
                ack.remove(title)
        for paragraph in list(ack.findall("p")):
            if not _element_has_content(paragraph):
                ack.remove(paragraph)
        if not _element_has_content(ack):
            back.remove(ack)


def prune_empty_jats_elements(article: etree._Element) -> None:
    """Drop template shells that have no text after PDF merge."""
    front = article.find("front")
    if front is not None:
        article_meta = front.find("article-meta")
        if article_meta is not None:
            _prune_aff_if_empty(article_meta)
            for tag in _PRUNE_WHEN_EMPTY:
                for node in list(article_meta.findall(tag)):
                    if not _element_has_content(node):
                        parent = node.getparent()
                        if parent is not None:
                            parent.remove(node)

    back = article.find("back")
    if back is not None:
        _prune_ack_shell(back)

    for element in list(article.iter()):
        if not is_element_node(element):
            continue
        local = xml_local_name(element)
        if local in _KEEP_STRUCTURE:
            continue
        if local not in _PRUNE_WHEN_EMPTY:
            continue
        if not _element_has_content(element):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
