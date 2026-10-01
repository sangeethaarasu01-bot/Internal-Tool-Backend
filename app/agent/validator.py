"""Stage 5: validate generated XML."""

from __future__ import annotations

from lxml import etree

from app.models.schema_map import SchemaMap
from app.utils.xml_helpers import parse_xml_string


class Validator:
    def validate(
        self,
        output_xml: str,
        template_xml: str,
        schema: SchemaMap,
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        try:
            out_root = parse_xml_string(output_xml)
        except etree.XMLSyntaxError as e:
            return False, [f"Output XML not well-formed: {e}"]

        for el in schema.elements:
            if not el.required:
                continue
            local = el.tag.split("/")[-1]
            found = out_root.xpath(f".//*[local-name()='{local}']")
            if not found:
                errors.append(f"Required element missing: {el.xpath}")
            elif el.data_type != "empty":
                if not any((n.text or "").strip() or len(n) for n in found):
                    errors.append(f"Required element empty: {el.xpath}")

        id_attrs = {
            (el.get("id") or "").strip()
            for el in out_root.xpath(".//*[@id]")
            if (el.get("id") or "").strip()
        }
        for xref in out_root.xpath(".//*[local-name()='xref'][@rid]"):
            rid = (xref.get("rid") or "").strip()
            if rid and rid not in id_attrs:
                errors.append(f"Broken xref: rid={rid} has no matching id")

        if schema.doctype and "DTD" in (schema.doctype or ""):
            try:
                dtd = etree.DTD(schema.doctype)
                if not dtd.validate(out_root):
                    errors.append("DTD validation failed (best-effort)")
            except Exception as e:
                errors.append(f"DTD validation skipped: {e}")

        return len(errors) == 0, errors
