"""Stage 5: validate generated XML."""

from __future__ import annotations

import re

from lxml import etree

from app.models.schema_map import SchemaMap


class Validator:
    def validate(
        self,
        output_xml: str,
        template_xml: str,
        schema: SchemaMap,
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        try:
            out_root = etree.fromstring(output_xml.encode("utf-8"))
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

        xref_rids = re.findall(r'<xref[^>]+rid="([^"]+)"', output_xml)
        id_attrs = set(re.findall(r'\bid="([^"]+)"', output_xml))
        for rid in xref_rids:
            if rid not in id_attrs:
                errors.append(f"Broken xref: rid={rid} has no matching id")

        if schema.doctype and "DTD" in (schema.doctype or ""):
            try:
                dtd = etree.DTD(schema.doctype)
                if not dtd.validate(out_root):
                    errors.append("DTD validation failed (best-effort)")
            except Exception as e:
                errors.append(f"DTD validation skipped: {e}")

        return len(errors) == 0, errors
