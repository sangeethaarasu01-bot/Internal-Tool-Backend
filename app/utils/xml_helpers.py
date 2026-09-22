"""XML parsing and manipulation helpers."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from app.utils.xml_text import (
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


def parse_xml_string(xml: str) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    return etree.fromstring(xml.encode("utf-8"), parser=parser)


def get_doctype_string(template_path: str | None, raw: str) -> str | None:
    m = re.search(r"<!DOCTYPE[^>]+>", raw, re.DOTALL | re.IGNORECASE)
    return m.group(0) if m else None


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


# IEEE/JATS-style hex character entities (see prompts/system.txt)
_IEEE_CHAR_ENTITIES: dict[str, str] = {
    "\u201c": "&#x201C;",
    "\u201d": "&#x201D;",
    "\u2018": "&#x2019;",
    "\u2019": "&#x2019;",
    "\u2013": "&#x2013;",
    "\u2014": "&#x2014;",
    "\u2026": "&#x2026;",
    "\u00a0": "&#x00A0;",
}


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
        if ch in _IEEE_CHAR_ENTITIES:
            parts.append(_IEEE_CHAR_ENTITIES[ch])
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


def post_process_ieee_entities(xml_str: str) -> str:
    """Encode punctuation/accented letters in serialized XML (avoids &amp;#x double-escape)."""
    xml_str = re.sub(r"&amp;(#x[0-9A-Fa-f]+;)", r"&\1", xml_str)
    return _encode_xml_text_content(xml_str)


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
    return xml_str
