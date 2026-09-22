"""Build figure/table XML fragments matching template."""

from __future__ import annotations

from xml.sax.saxutils import escape

from app.models.paper import Figure, Table
from app.models.schema_map import SchemaMap


class FigureTableHandler:
    def __init__(self, template: SchemaMap) -> None:
        self.template = template

    def build_figure_xml(self, fig: Figure, template_skel: dict | None = None) -> str:
        href = fig.image_path or fig.suggested_filename or f"{fig.id}.eps"
        return (
            f'<fig id="{escape(fig.id)}">'
            f"<label>FIGURE {fig.number}</label>"
            f"<caption><p>{escape(fig.caption)}</p></caption>"
            f'<graphic xlink:href="{escape(href)}"/>'
            f"</fig>"
        )

    def build_table_xml(self, table: Table, template_skel: dict | None = None) -> str:
        rows_xml = []
        for row in table.rows:
            cells = "".join(f"<td>{escape(c)}</td>" for c in row)
            rows_xml.append(f"<tr>{cells}</tr>")
        body = "".join(rows_xml)
        return (
            f'<table-wrap id="{escape(table.id)}">'
            f"<label>TABLE {table.number}</label>"
            f"<caption><p>{escape(table.caption or table.title)}</p></caption>"
            f"<table><tbody>{body}</tbody></table>"
            f"</table-wrap>"
        )
