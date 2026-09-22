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


def encode_ieee_text_entities(value: str) -> str:
    """IEEE hex entities for punctuation and accented letters — not PDF ligatures."""
    if not value:
        return value
    value = normalize_typographic_ligatures(value.replace("\u00ad", ""))
    out: list[str] = []
    for ch in value:
        if ch in _IEEE_CHAR_ENTITIES:
            out.append(_IEEE_CHAR_ENTITIES[ch])
        elif should_encode_as_hex_entity(ch):
            out.append(f"&#x{ord(ch):04X};")
        else:
            out.append(ch)
    return "".join(out)


def apply_ieee_entities_to_tree(root: etree._Element) -> None:
    """Walk element text/tail and apply IEEE entity encoding."""
    for elem in root.iter():
        if not is_element_node(elem):
            continue
        if elem.text:
            elem.text = encode_ieee_text_entities(elem.text)
        if elem.tail:
            elem.tail = encode_ieee_text_entities(elem.tail)


def post_process_ieee_entities(xml_str: str) -> str:
    """Replace any remaining Unicode chars in serialized XML with hex entities."""
    for uchar, ent in _IEEE_CHAR_ENTITIES.items():
        xml_str = xml_str.replace(uchar, ent)
    return xml_str


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
