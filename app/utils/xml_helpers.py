"""XML parsing and manipulation helpers."""

from __future__ import annotations

import re
from typing import Any

from lxml import etree


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
