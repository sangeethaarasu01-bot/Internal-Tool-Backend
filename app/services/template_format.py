"""Classify uploaded XML templates (IEEE JATS article vs DocBook 5.0 book)."""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from app.utils.xml_helpers import xml_local_name

DOCBOOK_NS = "http://docbook.org/ns/docbook"

IEEE_JATS_ARTICLE = "ieee_jats_article"
DOCBOOK_5_BOOK = "docbook_5_book"

SUPPORTED_TEMPLATE_FORMATS = (
    IEEE_JATS_ARTICLE,
    DOCBOOK_5_BOOK,
)


class UnsupportedTemplateRootError(ValueError):
    """Raised when the template root is not a supported vocabulary."""


@dataclass(frozen=True)
class TemplateRootInfo:
    local_name: str
    namespace_uri: str | None
    template_format: str
    version: str | None = None

    @property
    def description(self) -> str:
        if self.template_format == DOCBOOK_5_BOOK:
            ver = f" {self.version}" if self.version else ""
            return f"DocBook{ver} <book>"
        if self.template_format == IEEE_JATS_ARTICLE:
            return "IEEE JATS <article>"
        return f"<{self.local_name}>"


def _element_namespace_uri(element: etree._Element) -> str | None:
    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[0][1:]
    if element.nsmap:
        return element.nsmap.get(None)
    return None


def classify_template_root(element: etree._Element) -> TemplateRootInfo:
    """Detect supported template format from root element local name and namespace."""
    local = xml_local_name(element)
    namespace_uri = _element_namespace_uri(element)
    version = element.get("version")

    if local == "book":
        if namespace_uri == DOCBOOK_NS:
            return TemplateRootInfo(
                local_name="book",
                namespace_uri=namespace_uri,
                template_format=DOCBOOK_5_BOOK,
                version=version,
            )
        ns_hint = f" (namespace {namespace_uri!r})" if namespace_uri else ""
        raise UnsupportedTemplateRootError(
            f"Unsupported <book> template{ns_hint}. "
            f"DocBook 5.0 books must declare xmlns=\"{DOCBOOK_NS}\" on the root <book> element."
        )

    if local == "article":
        if namespace_uri == DOCBOOK_NS:
            raise UnsupportedTemplateRootError(
                "DocBook namespace on <article> is not supported; use IEEE JATS <article> without "
                f"the DocBook namespace, or a DocBook 5.0 <book> root."
            )
        return TemplateRootInfo(
            local_name="article",
            namespace_uri=namespace_uri,
            template_format=IEEE_JATS_ARTICLE,
            version=version,
        )

    supported = (
        "IEEE JATS <article> (no DocBook namespace on root), "
        f"DocBook 5.0 <book> (xmlns=\"{DOCBOOK_NS}\")"
    )
    ns_hint = f" in namespace {namespace_uri!r}" if namespace_uri else " (no default namespace)"
    raise UnsupportedTemplateRootError(
        f"Unsupported template root element <{local}>{ns_hint}. "
        f"Supported template formats: {supported}."
    )


def require_jats_article_template(element: etree._Element) -> TemplateRootInfo:
    """Ensure the template is an IEEE JATS article skeleton (for JATS XML generation)."""
    info = classify_template_root(element)
    if info.template_format != IEEE_JATS_ARTICLE:
        raise UnsupportedTemplateRootError(
            f"IEEE JATS XML generation requires an <article> template. "
            f"This file is a {info.description}, which is valid for template upload "
            f"and schema parsing but cannot be used as an IEEE JATS output skeleton."
        )
    return info
