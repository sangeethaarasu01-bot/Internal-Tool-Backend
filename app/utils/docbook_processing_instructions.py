"""Preserve DocBook template XML processing instructions through PDF merge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from lxml import etree

from app.utils.xml_helpers import is_element_node, xml_local_name


@dataclass(frozen=True)
class _PiRecord:
    parent_path: tuple[tuple[str, int], ...]
    child_index: int
    target: str
    data: str | None


def _element_sibling_index(elem: etree._Element) -> int:
    parent = elem.getparent()
    if parent is None:
        return 0
    name = xml_local_name(elem)
    index = 0
    for sibling in parent:
        if sibling is elem:
            return index
        if is_element_node(sibling) and xml_local_name(sibling) == name:
            index += 1
    return 0


def _element_path_key(elem: etree._Element) -> tuple[tuple[str, int], ...]:
    parts: list[tuple[str, int]] = []
    current: etree._Element | None = elem
    while current is not None and is_element_node(current):
        parts.append((xml_local_name(current), _element_sibling_index(current)))
        current = current.getparent()
    return tuple(reversed(parts))


def _find_element_by_path(root: etree._Element, path: tuple[tuple[str, int], ...]) -> etree._Element | None:
    if not path:
        return root
    if xml_local_name(root) != path[0][0]:
        return None
    current: etree._Element = root
    for local_name, sibling_index in path[1:]:
        matches = [
            child
            for child in current
            if is_element_node(child) and xml_local_name(child) == local_name
        ]
        if sibling_index >= len(matches):
            return None
        current = matches[sibling_index]
    return current


def snapshot_processing_instructions(root: etree._Element) -> list[_PiRecord]:
    """Record every processing instruction and its parent path + sibling index."""
    records: list[_PiRecord] = []
    for parent in root.iter():
        if not is_element_node(parent):
            continue
        for child_index, child in enumerate(parent):
            if child.tag is not etree.ProcessingInstruction:
                continue
            target = getattr(child, "target", None) or ""
            if not target:
                continue
            records.append(
                _PiRecord(
                    parent_path=_element_path_key(parent),
                    child_index=child_index,
                    target=str(target),
                    data=child.text,
                )
            )
    return records


def _pi_signature(node: etree._Element) -> tuple[str, str | None]:
    return (getattr(node, "target", "") or "", node.text)


def _restore_pi_sequence(parent: etree._Element, records: list[_PiRecord]) -> None:
    """Ensure PIs on ``parent`` match ``records`` in order (append missing at end)."""
    existing = [child for child in parent if child.tag is etree.ProcessingInstruction]
    wanted = [
        etree.ProcessingInstruction(rec.target, rec.data or "")
        for rec in sorted(records, key=lambda r: r.child_index)
    ]
    if len(existing) == len(wanted) and all(
        _pi_signature(existing[i]) == (wanted[i].target, wanted[i].text) for i in range(len(wanted))
    ):
        return
    for node in existing:
        parent.remove(node)
    for rec in sorted(records, key=lambda r: r.child_index):
        parent.append(etree.ProcessingInstruction(rec.target, rec.data or ""))


def _allow_pi_restore_for_parent_path(path: tuple[tuple[str, int], ...]) -> bool:
    """
    Keep PIs on preserved template skeleton (info, colophon, front matter).

    Drop PIs that lived on main-matter ``<chapter>`` nodes replaced by the PDF body.
    """
    names = [segment[0] for segment in path]
    if not names or names[0] != "book":
        return False
    if "chapter" not in names:
        return True
    chapter_index = names.index("chapter")
    between_book_and_chapter = names[1:chapter_index]
    return "part" in between_book_and_chapter


def restore_processing_instructions(
    root: etree._Element,
    snapshot: list[_PiRecord],
) -> int:
    """Re-insert template PIs on elements that still exist at the same structural path."""
    if not snapshot:
        return 0
    by_parent: dict[tuple[tuple[str, int], ...], list[_PiRecord]] = {}
    for rec in snapshot:
        if not _allow_pi_restore_for_parent_path(rec.parent_path):
            continue
        by_parent.setdefault(rec.parent_path, []).append(rec)

    restored = 0
    for parent_path, records in by_parent.items():
        parent = _find_element_by_path(root, parent_path)
        if parent is None:
            continue
        _restore_pi_sequence(parent, records)
        restored += len(records)
    return restored


def set_element_text_preserving_processing_instructions(
    element: etree._Element,
    text: str | None,
    *,
    sanitize: Callable[[str | None], str],
) -> None:
    """
    Update element text while keeping direct-child PIs and their relative order.

    Leading PIs keep their targets; printable text is placed on the tail of the
    last leading PI, or in ``element.text`` when no leading PI exists.
    """
    cleaned = sanitize(text)
    pis: list[etree._Element] = []
    for child in list(element):
        if child.tag is etree.ProcessingInstruction:
            pis.append(child)
        else:
            element.remove(child)

    if not pis:
        element.text = cleaned
        return

    element.text = None
    insert_at = 0
    for pi in pis:
        element.insert(insert_at, pi)
        insert_at += 1
    pis[-1].tail = cleaned
