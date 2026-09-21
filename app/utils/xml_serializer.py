"""Final XML serialization with hexadecimal quote character entities."""

from __future__ import annotations

import logging
from typing import Literal

from lxml import etree

from app.utils.xml_text import normalize_for_xml_serialization, should_encode_as_hex_entity

logger = logging.getLogger(__name__)

HEX_QUOTE_DOUBLE = "&#x22;"
HEX_QUOTE_SINGLE = "&#x27;"
_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
XLINK_NS = "http://www.w3.org/1999/xlink"
MML_NS = "http://www.w3.org/1998/Math/MathML"
_KNOWN_PREFIX_BY_URI = {
    XLINK_NS: "xlink",
    MML_NS: "mml",
}

_INLINE_TAGS = frozenset(
    {
        "bold",
        "italic",
        "sup",
        "sub",
        "xref",
        "inline-formula",
        "tex-math",
        "label",
        "kwd",
        "underline",
        "strike",
        "sc",
    }
)

NodeKind = Literal["element", "comment", "processing_instruction", "unsupported"]


class XmlSerializationError(ValueError):
    """Raised when the lxml tree contains a node that cannot be serialized."""


class _NsContext:
    """Namespace bindings used while serializing a document tree."""

    def __init__(self, root: etree._Element) -> None:
        self.root_nsmap: dict[str | None, str] = dict(root.nsmap or {})
        self.root_extras: dict[str | None, str] = _required_root_namespace_declarations(root)

    def effective_root_nsmap(self) -> dict[str | None, str]:
        merged = dict(self.root_nsmap)
        merged.update(self.root_extras)
        return merged

    def prefix_for_uri(self, uri: str, elem: etree._Element) -> str | None:
        canonical = _KNOWN_PREFIX_BY_URI.get(uri)
        if canonical:
            return canonical
        for nsmap in (elem.nsmap or {}, self.effective_root_nsmap()):
            for prefix, mapped_uri in nsmap.items():
                if mapped_uri == uri and prefix is not None:
                    return prefix
        return None


def _normalize_nsmap(nsmap: dict[str | None, str] | None) -> dict[str | None, str]:
    """Map lxml auto-generated ns0/ns1 prefixes to canonical IEEE/JATS prefixes."""
    normalized: dict[str | None, str] = {}
    for prefix, uri in (nsmap or {}).items():
        canonical = _KNOWN_PREFIX_BY_URI.get(uri)
        if canonical:
            normalized[canonical] = uri
        else:
            normalized[prefix] = uri
    return normalized


def _format_hex_char_entity(code: int) -> str:
    """IEEE-style uppercase hex character reference (minimum 4 digits for BMP)."""
    if code <= 0xFFFF:
        return f"&#x{code:04X};"
    return f"&#x{code:X};"


def _escape_xml_char(char: str) -> str:
    """Escape a single character for final IEEE JATS XML serialization."""
    if char == "&":
        return "&amp;"
    if char == "<":
        return "&lt;"
    if char == ">":
        return "&gt;"
    if char == '"':
        return HEX_QUOTE_DOUBLE
    if char == "'":
        return HEX_QUOTE_SINGLE
    if should_encode_as_hex_entity(char):
        return _format_hex_char_entity(ord(char))
    return char


def _is_insignificant_whitespace(value: str | None) -> bool:
    """True when text/tail is empty or only formatting whitespace between elements."""
    return not value or not value.strip()


def escape_for_xml_serialization(value: str | None) -> str:
    """Escape text/attribute content at XML write time only.

    Produces literal entity references in the serialized output:
    ``&#x27;``, ``&#x22;``, and ``&#x00E1;``-style hex entities for accented letters.
    """
    if not value:
        return ""
    normalized = normalize_for_xml_serialization(value)
    return "".join(_escape_xml_char(char) for char in normalized)


def _node_kind(node: etree._Element) -> NodeKind:
    tag = node.tag
    if isinstance(tag, str):
        return "element"
    if tag is etree.Comment:
        return "comment"
    if tag is etree.ProcessingInstruction:
        return "processing_instruction"
    return "unsupported"


def _parent_tag_name(node: etree._Element) -> str | None:
    parent = node.getparent()
    if parent is None:
        return None
    if isinstance(parent.tag, str):
        return _local_tag(parent.tag)
    return type(parent).__name__


def _element_path(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and isinstance(current.tag, str):
        parts.append(_local_tag(current.tag))
        current = current.getparent()
    return "/" + "/".join(reversed(parts)) if parts else "/"


def _unsupported_node_error(node: etree._Element, parent: etree._Element | None = None) -> XmlSerializationError:
    parent_tag = _parent_tag_name(parent) if parent is not None else _parent_tag_name(node)
    path = _element_path(node) if isinstance(node.tag, str) else None
    message = (
        f"Unsupported XML node type {type(node).__name__} "
        f"(tag={repr(node.tag)}, parent_tag={parent_tag!r}, path={path!r})"
    )
    logger.error(
        "XML serialization failed: type=%s tag=%r parent_tag=%s path=%s",
        type(node).__name__,
        node.tag,
        parent_tag,
        path,
    )
    return XmlSerializationError(message)


def _local_tag(tag: str) -> str:
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return str(tag)


def _clark_uri(name: str) -> str | None:
    if not name.startswith("{"):
        return None
    return name[1:].split("}", 1)[0]


def _required_root_namespace_declarations(root: etree._Element) -> dict[str | None, str]:
    """Return xmlns bindings that must be declared on the document root."""
    declared = dict(root.nsmap or {})
    required: dict[str | None, str] = {}

    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        clark_names = [node.tag, *node.attrib.keys()]
        for clark_name in clark_names:
            uri = _clark_uri(clark_name)
            if uri is None or uri == _XML_NAMESPACE:
                continue
            prefix = _KNOWN_PREFIX_BY_URI.get(uri)
            if prefix is None:
                continue
            if declared.get(prefix) == uri:
                continue
            required[prefix] = uri

    return required


def _namespace_declarations(elem: etree._Element, ctx: _NsContext) -> list[str]:
    """Return xmlns declarations newly introduced on ``elem``."""
    parent = elem.getparent()
    parent_nsmap = _normalize_nsmap(parent.nsmap if parent is not None else {})
    effective_nsmap = _normalize_nsmap(elem.nsmap)
    if parent is None:
        effective_nsmap.update(ctx.root_extras)

    parts: list[str] = []
    for prefix in sorted(effective_nsmap, key=lambda item: (item is not None, item or "")):
        uri = effective_nsmap[prefix]
        if parent_nsmap.get(prefix) == uri:
            continue
        if prefix is None:
            parts.append(f'xmlns="{uri}"')
        else:
            parts.append(f'xmlns:{prefix}="{uri}"')
    return parts


def _format_name(tag_or_attr: str, elem: etree._Element, ctx: _NsContext) -> str:
    if not isinstance(tag_or_attr, str):
        raise _unsupported_node_error(elem)
    if not tag_or_attr.startswith("{"):
        return tag_or_attr
    uri, local = tag_or_attr[1:].split("}", 1)
    if uri == _XML_NAMESPACE:
        return f"xml:{local}"
    prefix = ctx.prefix_for_uri(uri, elem)
    if prefix:
        return f"{prefix}:{local}"
    return local


def _format_attributes(elem: etree._Element, ctx: _NsContext) -> str:
    parts = _namespace_declarations(elem, ctx)
    for name, value in elem.attrib.items():
        attr_name = _format_name(name, elem, ctx)
        parts.append(f'{attr_name}="{escape_for_xml_serialization(value)}"')
    if not parts:
        return ""
    return " " + " ".join(parts)


def _serialize_comment(node: etree._Element, indent: str) -> str:
    text = node.text or ""
    if "--" in text:
        text = text.replace("--", "- -")
    return f"{indent}<!--{text}-->"


def _serialize_processing_instruction(node: etree._Element, indent: str) -> str:
    target = getattr(node, "target", None)
    if not target:
        raise _unsupported_node_error(node)
    content = node.text or ""
    if content:
        return f"{indent}<?{target} {content}?>"
    return f"{indent}<?{target}?>"


def _append_node_tail(
    node: etree._Element,
    lines: list[str],
    indent: str,
    *,
    pretty_print: bool,
) -> None:
    if not node.tail:
        return
    if pretty_print and _is_insignificant_whitespace(node.tail):
        return
    lines.append(f"{indent}{escape_for_xml_serialization(node.tail)}")


def _serialize_tree_node(
    node: etree._Element,
    lines: list[str],
    depth: int,
    pretty_print: bool,
    ctx: _NsContext,
    parent: etree._Element | None = None,
) -> None:
    kind = _node_kind(node)
    indent = "  " * depth if pretty_print else ""

    if kind == "element":
        _serialize_element(node, lines, depth, pretty_print, ctx)
        return
    if kind == "comment":
        lines.append(_serialize_comment(node, indent))
        return
    if kind == "processing_instruction":
        lines.append(_serialize_processing_instruction(node, indent))
        return
    raise _unsupported_node_error(node, parent)


def _has_block_children(elem: etree._Element) -> bool:
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        if _local_tag(child.tag) not in _INLINE_TAGS:
            return True
    return False


def _serialize_inline_children(elem: etree._Element, parts: list[str], ctx: _NsContext) -> None:
    for child in elem:
        kind = _node_kind(child)
        if kind == "element":
            parts.append(_serialize_inline_content(child, ctx))
        elif kind == "comment":
            parts.append(_serialize_comment(child, ""))
        elif kind == "processing_instruction":
            parts.append(_serialize_processing_instruction(child, ""))
        else:
            raise _unsupported_node_error(child, elem)
        if child.tail and not _is_insignificant_whitespace(child.tail):
            parts.append(escape_for_xml_serialization(child.tail))


def _serialize_inline(elem: etree._Element, depth: int, ctx: _NsContext) -> str:
    if not isinstance(elem.tag, str):
        raise _unsupported_node_error(elem)

    indent = "  " * depth
    tag = _format_name(elem.tag, elem, ctx)
    attrs = _format_attributes(elem, ctx)
    parts = [f"{indent}<{tag}{attrs}>"]
    if elem.text:
        parts.append(escape_for_xml_serialization(elem.text))
    _serialize_inline_children(elem, parts, ctx)
    parts.append(f"</{tag}>")
    return "".join(parts)


def _serialize_inline_content(elem: etree._Element, ctx: _NsContext) -> str:
    if not isinstance(elem.tag, str):
        raise _unsupported_node_error(elem)

    tag = _format_name(elem.tag, elem, ctx)
    attrs = _format_attributes(elem, ctx)
    parts = [f"<{tag}{attrs}>"]
    if elem.text:
        parts.append(escape_for_xml_serialization(elem.text))
    _serialize_inline_children(elem, parts, ctx)
    parts.append(f"</{tag}>")
    return "".join(parts)


def _serialize_element(
    elem: etree._Element,
    lines: list[str],
    depth: int,
    pretty_print: bool,
    ctx: _NsContext,
) -> None:
    if not isinstance(elem.tag, str):
        raise _unsupported_node_error(elem)

    children = list(elem)
    if children and not _has_block_children(elem):
        lines.append(_serialize_inline(elem, depth if pretty_print else 0, ctx))
        return

    indent = "  " * depth if pretty_print else ""
    child_indent = "  " * (depth + 1) if pretty_print else ""
    tag = _format_name(elem.tag, elem, ctx)
    attrs = _format_attributes(elem, ctx)

    if not children:
        text = escape_for_xml_serialization(elem.text or "")
        lines.append(f"{indent}<{tag}{attrs}>{text}</{tag}>")
        return

    lines.append(f"{indent}<{tag}{attrs}>")
    if elem.text and not (pretty_print and _is_insignificant_whitespace(elem.text)):
        lines.append(f"{child_indent}{escape_for_xml_serialization(elem.text)}")
    for child in children:
        _serialize_tree_node(child, lines, depth + 1, pretty_print, ctx, parent=elem)
        _append_node_tail(child, lines, child_indent, pretty_print=pretty_print)
    lines.append(f"{indent}</{tag}>")


def serialize_lxml_tree(
    element: etree._Element,
    *,
    xml_declaration: bool = True,
    encoding: str = "UTF-8",
    pretty_print: bool = True,
    doctype: str | None = None,
) -> str:
    """Serialize an lxml element tree with hex quote entities in text and attributes."""
    if not isinstance(element.tag, str):
        raise _unsupported_node_error(element)

    ctx = _NsContext(element)
    lines: list[str] = []
    if xml_declaration:
        lines.append(f'<?xml version="1.0" encoding="{encoding}"?>')
    if doctype:
        lines.append(doctype)
    _serialize_element(element, lines, 0, pretty_print, ctx)
    return "\n".join(lines)


def parse_xml_for_serialization(xml: str) -> etree._Element:
    """Parse XML and drop template formatting whitespace between elements."""
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.fromstring(xml.encode("utf-8"), parser)


def serialize_xml_text_nodes_with_hex_quotes(xml: str) -> str:
    """Serialize already-formed XML by re-parsing and re-emitting with hex quote entities."""
    root = parse_xml_for_serialization(xml)
    return serialize_lxml_tree(root, xml_declaration=False, pretty_print=True)


def serialize_tagged_output_for_preview(tagged_output: str) -> str:
    """Serialize semantic tagged output for API/XML preview without mutating stored IR."""
    if not tagged_output or not tagged_output.strip():
        return tagged_output
    try:
        return serialize_xml_text_nodes_with_hex_quotes(tagged_output)
    except etree.XMLSyntaxError:
        return tagged_output


def apply_final_xml_serialization_to_extraction_result(result: dict) -> dict:
    """Return an extraction result copy with serialized tagged_output for XML preview only."""
    import copy

    payload = copy.deepcopy(result)
    structure = payload.get("structure") or {}
    semantic = structure.get("semantic")
    if not isinstance(semantic, dict):
        return payload
    tagged = semantic.get("tagged_output")
    if isinstance(tagged, str) and tagged.strip():
        semantic["tagged_output"] = serialize_tagged_output_for_preview(tagged)
    return payload
