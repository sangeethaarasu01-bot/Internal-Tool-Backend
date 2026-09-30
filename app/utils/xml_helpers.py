"""XML parsing and manipulation helpers."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from app.utils.xml_text import (
    ieee_hex_entity_for_char,
    normalize_typographic_ligatures,
    should_encode_as_hex_entity,
)


def is_element_node(elem: etree._Element) -> bool:
    """True for real elements; comments/PIs use non-string .tag in lxml."""
    return isinstance(elem.tag, str)


def xml_local_name(elem: etree._Element) -> str:
    tag = elem.tag
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def iter_element_children(elem: etree._Element):
    for child in elem:
        if is_element_node(child):
            yield child


def reorder_contrib_group_author_comments(root: etree._Element) -> None:
    """IEEE front matter: ``author-comment`` follows all ``contrib`` nodes, before ``<aff>``."""
    for group in root.xpath(".//*[local-name()='contrib-group']"):
        if not is_element_node(group):
            continue
        comments = [
            child
            for child in list(group)
            if is_element_node(child) and xml_local_name(child) == "author-comment"
        ]
        if not comments:
            continue
        for node in comments:
            group.remove(node)
        for node in comments:
            group.append(node)


def parse_xml_string(xml: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    return etree.fromstring(xml.encode("utf-8"), parser=parser)


def get_doctype_string(template_path: str | None, raw: str) -> str | None:
    m = re.search(r"<!DOCTYPE[^>]+>", raw, re.DOTALL | re.IGNORECASE)
    return m.group(0) if m else None


# IEEE/JATS vendor templates use explicit open/close pairs, not XML empty-element syntax.
_SELF_CLOSING_TAG_RE = re.compile(
    r"<((?:[A-Za-z_][\w.-]*:)?[A-Za-z_][\w.-]*)(\s[^>/]*?)?\s*/>",
)


def expand_self_closing_empty_tags(xml_str: str) -> str:
    """Rewrite ``<tag/>`` and ``<tag attr="x"/>`` to ``<tag></tag>`` / ``<tag attr="x"></tag>``."""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        attrs = match.group(2) or ""
        return f"<{name}{attrs}></{name}>"

    return _SELF_CLOSING_TAG_RE.sub(_replace, xml_str)


# IEEE figures/tables: these empty elements stay self-closing (unlike xplore-* front matter).
_IEEE_SELF_CLOSING_EMPTY_TAGS = frozenset(
    {
        "graphic",
        "col",
        "counts",
        "fig-count",
        "table-count",
        "equation-count",
        "ref-count",
        "page-count",
        "word-count",
    }
)


def collapse_ieee_empty_element_tags(xml_str: str) -> str:
    """Rewrite empty ``<tag></tag>`` pairs to ``<tag/>`` for IEEE graphic/table/count elements."""
    for local_tag in _IEEE_SELF_CLOSING_EMPTY_TAGS:
        escaped = re.escape(local_tag)
        pattern = (
            rf"<((?:[A-Za-z_][\w.-]*:)?{escaped})(\s[^>]*)?></(?:[A-Za-z_][\w.-]*:)?{escaped}>"
        )
        xml_str = re.sub(pattern, r"<\1\2/>", xml_str)
    return xml_str


def format_ieee_empty_element_tags(xml_str: str) -> str:
    """Front matter: explicit empty pairs; graphics/tables/counts: self-closing."""
    return collapse_ieee_empty_element_tags(expand_self_closing_empty_tags(xml_str))


def element_to_skeleton(elem: etree._Element, path: str = "") -> dict[str, Any]:
    tag = xml_local_name(elem)
    current_path = f"{path}/{tag}" if path else tag
    text = (elem.text or "").strip()
    if len(text) > 120:
        text = text[:120] + "..."
    attrs = {k: v for k, v in elem.attrib.items()}
    children = [element_to_skeleton(c, current_path) for c in iter_element_children(elem)]
    return {
        "tag": tag,
        "path": current_path,
        "attributes": attrs,
        "sample_text": text,
        "children": children,
    }


def escape_xml_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def normalize_text_for_xml_dom(value: str) -> str:
    """PDF typography cleanup for lxml text nodes (entities applied at serialize time)."""
    if not value:
        return value
    return normalize_typographic_ligatures(value.replace("\u00ad", ""))


def clean_extracted_abstract(text: str) -> str:
    """Strip IEEE 'Abstract—' label and PDF line-break hyphens from abstract text."""
    text = normalize_text_for_xml_dom(text)
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(
        r"^(?:Abstract|ABSTRACT)\s*[—–\-\u2013\u2014:]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^[—–\-\u2013\u2014]\s*", "", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    return text.strip()


def _encode_plain_text_chunk(chunk: str) -> str:
    parts: list[str] = []
    k = 0
    while k < len(chunk):
        if chunk[k] == "&":
            ent_end = chunk.find(";", k)
            if ent_end != -1:
                ent = chunk[k : ent_end + 1]
                if re.match(r"&(?:#\d+|#x[0-9A-Fa-f]+|amp|lt|gt|quot|apos);", ent):
                    parts.append(ent)
                    k = ent_end + 1
                    continue
        ch = chunk[k]
        entity = ieee_hex_entity_for_char(ch)
        if entity:
            parts.append(entity)
        elif should_encode_as_hex_entity(ch):
            parts.append(f"&#x{ord(ch):04X};")
        else:
            parts.append(ch)
        k += 1
    return "".join(parts)


def encode_ieee_text_entities(value: str) -> str:
    """IEEE hex entities for punctuation and accented letters — not PDF ligatures."""
    if not value:
        return value
    return _encode_plain_text_chunk(normalize_text_for_xml_dom(value))


def _encode_xml_text_content(xml_str: str) -> str:
    """Apply IEEE entity rules to text between XML tags (not inside tags)."""
    out: list[str] = []
    i = 0
    n = len(xml_str)
    while i < n:
        if xml_str[i] == "<":
            j = xml_str.find(">", i)
            if j == -1:
                out.append(xml_str[i:])
                break
            out.append(xml_str[i : j + 1])
            i = j + 1
            continue
        j = i
        while j < n and xml_str[j] != "<":
            j += 1
        chunk = xml_str[i:j]
        if chunk:
            out.append(_encode_plain_text_chunk(chunk))
        i = j
    return "".join(out)


def apply_ieee_entities_to_tree(root: etree._Element) -> None:
    """Normalize PDF typography in the DOM; hex entities are applied when serializing."""
    for elem in root.iter():
        if not is_element_node(elem):
            continue
        if elem.text:
            elem.text = normalize_text_for_xml_dom(elem.text)
        if elem.tail:
            elem.tail = normalize_text_for_xml_dom(elem.tail)


# PDF/list bullets that must appear as &#x2022; inside <label> (IEEE list markers).
_LABEL_BULLET_CHARS = "\u2022\u00b7\u2219\u25e6\u2043\u2217"


def _encode_list_label_markers(xml_str: str) -> str:
    """Force IEEE hex entities for list-item label markers (bullet, asterisk)."""
    bullet_pat = rf"<label>\s*([{re.escape(_LABEL_BULLET_CHARS)}])\s*</label>"
    xml_str = re.sub(bullet_pat, "<label>&#x2022;</label>", xml_str)
    xml_str = re.sub(r"<label>\s*\*\s*</label>", "<label>&#x002A;</label>", xml_str)
    return xml_str


def post_process_ieee_entities(xml_str: str) -> str:
    """Encode punctuation/accented letters in serialized XML (avoids &amp;#x double-escape)."""
    xml_str = re.sub(r"&amp;(#x[0-9A-Fa-f]+;)", r"&\1", xml_str)
    xml_str = _encode_xml_text_content(xml_str)
    return _encode_list_label_markers(xml_str)


def finalize_ieee_xml(xml: str) -> str:
    """Re-serialize XML with IEEE hex entities (front matter, body, and template text)."""
    doctype = get_doctype_string(None, xml)
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    root = etree.fromstring(xml.encode("utf-8"), parser=parser)
    apply_ieee_entities_to_tree(root)
    reorder_contrib_group_author_comments(root)
    tree = etree.ElementTree(root)
    return post_process_ieee_entities(serialize_tree(tree, doctype=doctype))


def serialize_tree(tree: etree._ElementTree, doctype: str | None = None) -> str:
    xml_bytes = etree.tostring(
        tree,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    xml_str = xml_bytes.decode("utf-8")
    if doctype and "<!DOCTYPE" not in xml_str:
        xml_str = xml_str.replace(
            "?>",
            f"?>\n{doctype}",
            1,
        )
    return format_ieee_empty_element_tags(xml_str)
