"""Split DocBook 5.0 book XML into chapter-level (and section-level) storage units."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from lxml import etree

from app.models.docbook_template import DocBookBookMetadata
from app.services.docbook_template import extract_docbook_book_metadata, parse_docbook_book_tree
from app.services.mongo_bson_limits import mongodb_max_payload_bytes, payload_within_limit
from app.services.template_format import DOCBOOK_NS, classify_template_root
from app.utils.xml_helpers import iter_element_children, xml_local_name
from app.utils.xml_serializer import serialize_lxml_tree

ChunkKind = Literal[
    "chapter",
    "appendix",
    "preface",
    "colophon",
    "dedication",
    "bibliography",
    "glossary",
    "index",
    "part_intro",
    "other",
]

# Top-level book content we never drop (inside book or part).
_CONTENT_LOCAL_NAMES = frozenset(
    {
        "chapter",
        "appendix",
        "preface",
        "colophon",
        "dedication",
        "bibliography",
        "glossary",
        "index",
        "article",
        "reference",
        "part",
    }
)

_SECTION_LOCAL = "section"


class DocBookChunkingError(ValueError):
    """Book could not be split safely."""


@dataclass
class HierarchyNode:
    node_id: str
    kind: str
    tag: str
    title: str | None = None
    label: str | None = None
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)


@dataclass
class BookChunk:
    document_id: str
    kind: ChunkKind
    title: str | None
    label: str | None
    sequence: int
    parent_part_id: str | None
    xml_fragment: str
    payload_bytes: int
    split_parent_id: str | None = None
    split_index: int | None = None


@dataclass
class BookManifest:
    book_id: str
    title: str | None
    subtitle: str | None
    authors: list[str]
    publisher: str | None
    publication_year: str | None
    isbns: list[dict[str, str | None]]
    doi: str | None
    source_document_format: str
    output_document_format: str
    extraction_id: str | None
    total_unit_count: int
    hierarchy: list[dict[str, Any]]
    units: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "authors": self.authors,
            "publisher": self.publisher,
            "publication_year": self.publication_year,
            "isbns": self.isbns,
            "doi": self.doi,
            "source_document_format": self.source_document_format,
            "output_document_format": self.output_document_format,
            "extraction_id": self.extraction_id,
            "total_unit_count": self.total_unit_count,
            "hierarchy": self.hierarchy,
            "units": self.units,
        }


def _slug_id(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "-", value.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "book"


def derive_book_id(metadata: DocBookBookMetadata, extraction_id: str) -> str:
    if metadata.doi:
        return metadata.doi.strip()
    title = (metadata.title or "").strip()
    if title:
        return _slug_id(title)
    return extraction_id


def _element_title(element: etree._Element) -> str | None:
    for child in iter_element_children(element):
        if xml_local_name(child) == "title":
            text = " ".join(child.itertext()).strip()
            return text or None
    return None


def _classify_kind(local: str) -> ChunkKind:
    if local in _CONTENT_LOCAL_NAMES:
        return local if local != "part" else "part_intro"  # type: ignore[return-value]
    return "other"


def _book_namespace_map(root: etree._Element) -> dict[str | None, str]:
    """Collect namespace declarations needed to round-trip book subtrees (e.g. xlink)."""
    nsmap: dict[str | None, str] = {None: DOCBOOK_NS}
    if root.nsmap:
        for prefix, uri in root.nsmap.items():
            nsmap[prefix] = uri
    xlink_ns = "http://www.w3.org/1999/xlink"
    for el in root.iter():
        for attr_name in el.attrib:
            if attr_name.startswith("{http://www.w3.org/1999/xlink}"):
                nsmap["xlink"] = xlink_ns
            elif attr_name.startswith("xlink:"):
                nsmap["xlink"] = xlink_ns
    return nsmap


def _serialize_fragment(element: etree._Element, nsmap: dict[str | None, str]) -> str:
    """Serialize a book subtree with inherited namespace declarations on the fragment root."""
    copied = etree.fromstring(etree.tostring(element))
    existing = copied.nsmap or {}
    for prefix, uri in nsmap.items():
        if prefix is None:
            continue
        if prefix not in existing:
            copied.set(f"xmlns:{prefix}", uri)
    return serialize_lxml_tree(
        copied,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=None,
    )


def _direct_sections(element: etree._Element) -> list[etree._Element]:
    return [
        child
        for child in iter_element_children(element)
        if xml_local_name(child) == _SECTION_LOCAL
    ]


def _split_by_sections(
    element: etree._Element,
    *,
    base_document_id: str,
    max_bytes: int,
    nsmap: dict[str, str],
) -> list[BookChunk]:
    """Split an oversized unit at nested ``section`` boundaries."""
    sections = _direct_sections(element)
    if not sections:
        raise DocBookChunkingError(
            f"Unit {base_document_id} exceeds payload limit and has no child sections to split."
        )

    local = xml_local_name(element)
    title = _element_title(element)
    label = element.get("label") or element.get(f"{{{DOCBOOK_NS}}}label")
    chunks: list[BookChunk] = []

    # Header: element tag + non-section children (title, para before first section, etc.)
    header_children: list[etree._Element] = []
    for child in iter_element_children(element):
        if xml_local_name(child) == _SECTION_LOCAL:
            break
        header_children.append(child)

    section_batches: list[list[etree._Element]] = []
    current_batch: list[etree._Element] = []
    current_size = 0

    def batch_size(batch: list[etree._Element], include_header: bool) -> int:
        wrapper = etree.Element(element.tag, nsmap=nsmap)
        for attr, val in element.attrib.items():
            wrapper.set(attr, val)
        if include_header:
            for node in header_children:
                wrapper.append(etree.fromstring(etree.tostring(node)))
        for node in batch:
            wrapper.append(etree.fromstring(etree.tostring(node)))
        return len(_serialize_fragment(wrapper, nsmap).encode("utf-8"))

    for section in sections:
        trial = current_batch + [section]
        size = batch_size(trial, include_header=not chunks)
        if current_batch and size > max_bytes:
            section_batches.append(current_batch)
            current_batch = [section]
        else:
            current_batch = trial
    if current_batch:
        section_batches.append(current_batch)

    for idx, batch in enumerate(section_batches, start=1):
        wrapper = etree.Element(element.tag, nsmap=nsmap)
        for attr, val in element.attrib.items():
            wrapper.set(attr, val)
        if idx == 1:
            for node in header_children:
                wrapper.append(etree.fromstring(etree.tostring(node)))
        for node in batch:
            wrapper.append(etree.fromstring(etree.tostring(node)))
        frag = _serialize_fragment(wrapper, nsmap)
        payload = len(frag.encode("utf-8"))
        if not payload_within_limit(payload, limit=max_bytes):
            raise DocBookChunkingError(
                f"Section slice {base_document_id}/s-{idx} still exceeds limit ({payload} bytes)."
            )
        doc_id = f"{base_document_id}/s-{idx}"
        chunks.append(
            BookChunk(
                document_id=doc_id,
                kind=_classify_kind(local),
                title=title,
                label=label,
                sequence=0,
                parent_part_id=None,
                xml_fragment=frag,
                payload_bytes=payload,
                split_parent_id=base_document_id,
                split_index=idx,
            )
        )
    return chunks


def _make_chunk(
    element: etree._Element,
    *,
    document_id: str,
    kind: ChunkKind,
    sequence: int,
    parent_part_id: str | None,
    max_bytes: int,
    nsmap: dict[str, str],
) -> list[BookChunk]:
    frag = _serialize_fragment(element, nsmap)
    payload = len(frag.encode("utf-8"))
    if payload_within_limit(payload, limit=max_bytes):
        return [
            BookChunk(
                document_id=document_id,
                kind=kind,
                title=_element_title(element),
                label=element.get("label"),
                sequence=sequence,
                parent_part_id=parent_part_id,
                xml_fragment=frag,
                payload_bytes=payload,
            )
        ]
    return _split_by_sections(
        element,
        base_document_id=document_id,
        max_bytes=max_bytes,
        nsmap=nsmap,
    )


def _walk_units(
    parent: etree._Element,
    *,
    book_id: str,
    counters: dict[str, int],
    parent_part_id: str | None,
    hierarchy_nodes: dict[str, HierarchyNode],
    chunks_out: list[BookChunk],
    max_bytes: int,
    nsmap: dict[str, str],
) -> None:
    for child in iter_element_children(parent):
        local = xml_local_name(child)
        if local == "info":
            continue
        if local == "part":
            counters["part"] = counters.get("part", 0) + 1
            part_seq = counters["part"]
            part_label = child.get("label")
            part_title = _element_title(child)
            part_id = child.get("xml:id") or f"{book_id}/part-{part_seq}"
            hierarchy_nodes[part_id] = HierarchyNode(
                node_id=part_id,
                kind="part",
                tag="part",
                title=part_title,
                label=part_label,
                parent_id=None,
            )
            _walk_units(
                child,
                book_id=book_id,
                counters=counters,
                parent_part_id=part_id,
                hierarchy_nodes=hierarchy_nodes,
                chunks_out=chunks_out,
                max_bytes=max_bytes,
                nsmap=nsmap,
            )
            continue

        if local not in _CONTENT_LOCAL_NAMES and local != "title":
            counters["other"] = counters.get("other", 0) + 1
            kind: ChunkKind = "other"
            key = f"misc-{counters['other']}"
        else:
            if local == "title":
                continue
            kind = _classify_kind(local)
            counters[local] = counters.get(local, 0) + 1
            key = f"{local}-{counters[local]}"

        xml_id = child.get("xml:id")
        document_id = xml_id if xml_id else f"{book_id}/{key}"
        if parent_part_id and parent_part_id in hierarchy_nodes:
            hierarchy_nodes[parent_part_id].children.append(document_id)

        hierarchy_nodes[document_id] = HierarchyNode(
            node_id=document_id,
            kind=kind,
            tag=local,
            title=_element_title(child),
            label=child.get("label"),
            parent_id=parent_part_id,
        )

        sequence = len(chunks_out) + 1
        produced = _make_chunk(
            child,
            document_id=document_id,
            kind=kind,
            sequence=sequence,
            parent_part_id=parent_part_id,
            max_bytes=max_bytes,
            nsmap=nsmap,
        )
        for chunk in produced:
            if chunk.sequence == 0:
                chunk.sequence = len(chunks_out) + 1
            chunks_out.append(chunk)


def chunk_docbook_book_xml(
    book_xml: str,
    *,
    extraction_id: str,
    max_payload_bytes: int | None = None,
) -> tuple[BookManifest, list[BookChunk]]:
    """
    Parse a DocBook 5.0 book and produce a metadata manifest plus storage chunks.
    """
    cap = max_payload_bytes if max_payload_bytes is not None else mongodb_max_payload_bytes()
    try:
        root = etree.fromstring(book_xml.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        raise DocBookChunkingError(f"Invalid DocBook XML: {exc}") from exc

    info = classify_template_root(root)
    if info.template_format != "docbook_5_book":
        raise DocBookChunkingError("Root element must be a DocBook 5.0 <book>.")

    parse_result = parse_docbook_book_tree(root)
    metadata = parse_result.metadata
    book_id = derive_book_id(metadata, extraction_id)

    nsmap = _book_namespace_map(root)

    hierarchy_nodes: dict[str, HierarchyNode] = {}
    chunks: list[BookChunk] = []
    counters: dict[str, int] = {}

    _walk_units(
        root,
        book_id=book_id,
        counters=counters,
        parent_part_id=None,
        hierarchy_nodes=hierarchy_nodes,
        chunks_out=chunks,
        max_bytes=cap,
        nsmap=nsmap,
    )

    if not chunks:
        raise DocBookChunkingError("No book content units found to persist.")

    isbns = [
        {"kind": ident.kind, "role": ident.role, "value": ident.value}
        for ident in metadata.isbns
    ]

    unit_records: list[dict[str, Any]] = []
    for chunk in chunks:
        unit_records.append(
            {
                "document_id": chunk.document_id,
                "kind": chunk.kind,
                "title": chunk.title,
                "label": chunk.label,
                "sequence": chunk.sequence,
                "parent_part_id": chunk.parent_part_id,
                "payload_bytes": chunk.payload_bytes,
                "status": "pending",
                "split_parent_id": chunk.split_parent_id,
                "split_index": chunk.split_index,
            }
        )

    hierarchy_list = [
        {
            "node_id": node.node_id,
            "kind": node.kind,
            "tag": node.tag,
            "title": node.title,
            "label": node.label,
            "parent_id": node.parent_id,
            "children": node.children,
        }
        for node in hierarchy_nodes.values()
    ]

    chapter_count = sum(1 for c in chunks if c.kind == "chapter" and c.split_parent_id is None)

    manifest = BookManifest(
        book_id=book_id,
        title=metadata.title,
        subtitle=metadata.subtitle,
        authors=list(metadata.authors),
        publisher=metadata.publisher,
        publication_year=metadata.copyright_year,
        isbns=isbns,
        doi=metadata.doi,
        source_document_format="docbook_5",
        output_document_format="docbook_5",
        extraction_id=extraction_id,
        total_unit_count=len(chunks),
        hierarchy=hierarchy_list,
        units=unit_records,
    )
    manifest.units  # expose chapter_count via manifest dict in tests
    _ = chapter_count
    return manifest, chunks


def _merge_split_slices(slice_xml_list: list[str]) -> etree._Element:
    if not slice_xml_list:
        raise DocBookChunkingError("No slices to merge.")
    base = etree.fromstring(slice_xml_list[0].encode("utf-8"))
    for extra in slice_xml_list[1:]:
        node = etree.fromstring(extra.encode("utf-8"))
        for child in iter_element_children(node):
            if xml_local_name(child) == _SECTION_LOCAL:
                base.append(child)
    return base


def reassemble_book_xml_from_chunks(manifest: dict[str, Any], chunks_by_id: dict[str, str]) -> str:
    """Rebuild book XML from stored fragments (ordered by manifest unit sequence)."""
    units = sorted(
        manifest.get("units") or [],
        key=lambda u: int(u.get("sequence") or 0),
    )
    if not units:
        raise DocBookChunkingError("Manifest has no units.")

    reassemble_nsmap: dict[str | None, str] = {None: DOCBOOK_NS}
    for unit in units:
        frag = chunks_by_id.get(unit["document_id"])
        if not frag:
            continue
        try:
            probe = etree.fromstring(frag.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for prefix, uri in (probe.nsmap or {}).items():
            reassemble_nsmap[prefix] = uri

    book = etree.Element(
        f"{{{DOCBOOK_NS}}}book",
        nsmap=reassemble_nsmap,
        version="5.0",
    )
    handled_split_parents: set[str] = set()

    for unit in units:
        split_parent = unit.get("split_parent_id")
        if split_parent:
            if split_parent in handled_split_parents:
                continue
            slices = [
                u for u in units if u.get("split_parent_id") == split_parent
            ]
            slices.sort(key=lambda u: int(u.get("split_index") or 0))
            slice_xml = [
                chunks_by_id[u["document_id"]]
                for u in slices
                if u["document_id"] in chunks_by_id
            ]
            if not slice_xml:
                continue
            book.append(_merge_split_slices(slice_xml))
            handled_split_parents.add(split_parent)
            continue

        frag = chunks_by_id.get(unit["document_id"])
        if not frag:
            continue
        book.append(etree.fromstring(frag.encode("utf-8")))

    return serialize_lxml_tree(
        book,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
        doctype=None,
    )
