"""Render semantic document IR as tagged intermediate representation HTML."""

from __future__ import annotations

from app.constants.ir_types import IR_DISPLAY_MATH, IR_INLINE_MATH, IR_LIST, IR_LIST_ITEM, IR_TABLE
from app.models.ir_schema import IRInlineMathElement, IRNode, IRTextElement
from app.models.semantic_document import SemanticDocument, SemanticSection
from app.utils.xml_text import escape_xml_text


def _esc(text: str) -> str:
    return escape_xml_text(text)


def _attrs(element: IRNode) -> str:
    parts = [
        f'data-type="{_esc(element.type)}"',
        f'data-source="{",".join(element.source_block_ids)}"',
        f'data-pages="{",".join(str(p) for p in element.page_numbers)}"',
        f'data-confidence="{element.confidence:.2f}"',
    ]
    if element.level is not None:
        parts.append(f'data-level="{element.level}"')
    if element.unknown_reason:
        parts.append(f'data-reason="{_esc(element.unknown_reason)}"')
    if element.label:
        parts.append(f'data-label="{_esc(element.label)}"')
    if element.list_type:
        parts.append(f'list-type="{_esc(element.list_type)}"')
        parts.append(f'data-list-type="{_esc(element.list_type)}"')
    if element.list_marker:
        parts.append(f'data-list-marker="{_esc(element.list_marker)}"')
    if element.detection_reason:
        parts.append(f'data-detection-reason="{_esc(element.detection_reason)}"')
    if element.bbox:
        bbox = ", ".join(f"{v:.2f}" for v in element.bbox)
        parts.append(f'data-bbox="[{bbox}]"')
    return " ".join(parts)


def _render_inline_elements(elements: list[IRTextElement | IRInlineMathElement], indent: int) -> str:
    """Render composable inline elements inside a block-level tag."""
    pad = " " * indent
    parts: list[str] = []
    for element in elements:
        if element.type == "text":
            parts.append(_esc(element.value))
        elif element.type == IR_INLINE_MATH:
            parts.append(
                f'{pad}  <inline-formula data-type="inline_math">'
                f'<tex-math notation="LaTeX">{_esc(element.latex)}</tex-math>'
                f"</inline-formula>"
            )
    if len(parts) == 1 and not parts[0].startswith("<"):
        return parts[0]
    return "\n".join(parts)


def _render_element(element: IRNode, indent: int = 2) -> str:
    pad = " " * indent
    open_tag = f"<{element.tag} {_attrs(element)}>"
    close_tag = f"</{element.tag}>"

    if element.keywords:
        inner = "\n".join(
            f'{pad}  <kwd data-source="{_esc(",".join(element.source_block_ids))}">{_esc(kw)}</kwd>'
            for kw in element.keywords
        )
        return f"{pad}{open_tag}\n{inner}\n{pad}{close_tag}"

    if element.type == IR_DISPLAY_MATH and element.latex is not None:
        lines = [f"{pad}{open_tag}"]
        if element.label:
            lines.append(f"{pad}  <label {_attrs(element)}>{_esc(element.label)}</label>")
        lines.append(f'{pad}  <tex-math notation="LaTeX">{_esc(element.latex)}</tex-math>')
        lines.append(f"{pad}{close_tag}")
        return "\n".join(lines)

    if element.type == IR_TABLE and element.rows:
        lines = [f"{pad}{open_tag}"]
        if element.elements:
            caption = _render_inline_elements(element.elements, indent + 4)
            lines.append(f"{pad}  <caption {_attrs(element)}>{caption}</caption>")
        lines.append(f"{pad}  <table>")
        header_row, data_rows = element.rows[0], element.rows[1:]
        lines.append(f"{pad}    <thead>")
        lines.append(f"{pad}      <tr>")
        for cell in header_row:
            lines.append(f"{pad}        <th>{_esc(cell)}</th>")
        lines.append(f"{pad}      </tr>")
        lines.append(f"{pad}    </thead>")
        if data_rows:
            lines.append(f"{pad}    <tbody>")
            for row in data_rows:
                lines.append(f"{pad}      <tr>")
                for cell in row:
                    lines.append(f"{pad}        <td>{_esc(cell)}</td>")
                lines.append(f"{pad}      </tr>")
            lines.append(f"{pad}    </tbody>")
        lines.append(f"{pad}  </table>")
        lines.append(f"{pad}{close_tag}")
        return "\n".join(lines)

    if element.type == "figure" and element.children:
        lines = [f"{pad}{open_tag}"]
        for child in element.children:
            lines.append(_render_element(child, indent + 2))
        lines.append(f"{pad}{close_tag}")
        return "\n".join(lines)

    if element.type == IR_LIST and element.children:
        lines = [f"{pad}{open_tag}"]
        for child in element.children:
            lines.append(_render_element(child, indent + 2))
        lines.append(f"{pad}{close_tag}")
        return "\n".join(lines)

    if element.type == IR_LIST_ITEM and element.children:
        lines = [f"{pad}{open_tag}"]
        for child in element.children:
            lines.append(_render_element(child, indent + 2))
        lines.append(f"{pad}{close_tag}")
        return "\n".join(lines)

    if element.children and element.type == "abstract":
        inner = "\n".join(_render_element(child, indent + 2) for child in element.children)
        return f"{pad}{open_tag}\n{inner}\n{pad}{close_tag}"

    if element.type in {
        "author",
        "affiliation",
        "title",
        "date_history",
        "corresponding_author",
        "reference",
        "figure_caption",
        "table_caption",
    }:
        content = _render_inline_elements(element.elements, indent + 2) if element.elements else _esc(element.text)
        return f"{pad}{open_tag}{content}{close_tag}"

    if element.elements:
        inline = _render_inline_elements(element.elements, indent + 2)
        if inline.startswith("<"):
            return f"{pad}{open_tag}\n{inline}\n{pad}{close_tag}"
        return f"{pad}{open_tag}\n{pad}  {inline}\n{pad}{close_tag}"

    if element.text:
        return f"{pad}{open_tag}\n{pad}  {_esc(element.text)}\n{pad}{close_tag}"

    return f"{pad}{open_tag}{close_tag}"


def _render_section(section: SemanticSection, indent: int = 2) -> str:
    pad = " " * indent
    level_attr = f' data-level="{section.level}"' if section.level else ""
    heading_type = "SUBSECTION_HEADING" if section.level > 1 else "SECTION_HEADING"
    heading_attrs = (
        f'data-source="{",".join(section.heading_element.source_block_ids)}" '
        f'data-type="{heading_type}"'
    )
    lines = [
        f'{pad}<sec{level_attr} data-heading-source="{",".join(section.heading_element.source_block_ids)}">',
    ]
    if section.heading_element.label:
        lines.append(f'{pad}  <label {heading_attrs}>{_esc(section.heading_element.label)}</label>')
    lines.append(f'{pad}  <title {heading_attrs}>{_esc(section.heading)}</title>')
    for item in section.content:
        lines.append(_render_element(item, indent + 2))
    for paragraph in section.paragraphs:
        if paragraph not in section.content:
            lines.append(_render_element(paragraph, indent + 2))
    for subsection in section.subsections:
        lines.append(_render_section(subsection, indent + 2))
    lines.append(f"{pad}</sec>")
    return "\n".join(lines)


def render_semantic_document(document: SemanticDocument) -> str:
    lines = ['<article data-type="document">', "  <front>"]

    front = document.front
    if front.journal_header:
        lines.append(_render_element(front.journal_header, 4))
    if front.page_number:
        lines.append(_render_element(front.page_number, 4))
    if front.title:
        lines.append(_render_element(front.title, 4))
    if front.authors:
        lines.append("    <contrib-group>")
        for author in front.authors:
            lines.append(_render_element(author, 6))
        lines.append("    </contrib-group>")
    for aff in front.affiliations:
        lines.append(_render_element(aff, 4))
    if front.date_history:
        lines.append(_render_element(front.date_history, 4))
    if front.corresponding_author:
        lines.append(_render_element(front.corresponding_author, 4))
    if front.abstract:
        lines.append(_render_element(front.abstract, 4))
    if front.keywords:
        lines.append(_render_element(front.keywords, 4))
    for item in front.other:
        lines.append(_render_element(item, 4))

    lines.append("  </front>")
    lines.append("  <body>")

    for section in document.body.sections:
        lines.append(_render_section(section, 4))
    for paragraph in document.body.loose_paragraphs:
        lines.append(_render_element(paragraph, 4))

    lines.append("  </body>")

    if document.back.reference_list or document.back.references:
        lines.append("  <back>")
        if document.back.reference_list:
            lines.append(_render_element(document.back.reference_list, 4))
        lines.append("    <ref-list>")
        for ref in document.back.references:
            lines.append(_render_element(ref, 6))
        lines.append("    </ref-list>")
        lines.append("  </back>")

    if document.unknown:
        lines.append("  <unknown>")
        for item in document.unknown:
            lines.append(_render_element(item, 4))
        lines.append("  </unknown>")

    lines.append("</article>")
    return "\n".join(lines)
