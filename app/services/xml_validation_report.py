"""Spec validation levels V1–V2 (well-formed + optional DTD) for generated XML."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree


@dataclass
class XmlValidationReport:
    well_formed: bool
    dtd_validated: bool = False
    dtd_passed: bool | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_generated_xml(
    xml_content: str,
    *,
    dtd_path: str | Path | None = None,
) -> XmlValidationReport:
    """Parse XML and optionally validate against a project DTD path."""
    errors: list[str] = []
    warnings: list[str] = []
    text = (xml_content or "").lstrip("\ufeff")
    if not text.strip():
        return XmlValidationReport(
            well_formed=False,
            errors=["Empty XML output"],
        )

    try:
        document = etree.fromstring(text.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        return XmlValidationReport(well_formed=False, errors=[f"XML syntax: {exc}"])

    report = XmlValidationReport(well_formed=True)
    if not dtd_path:
        return report

    dtd_file = Path(dtd_path)
    if not dtd_file.is_file():
        report.warnings.append(f"DTD not found at {dtd_file}; skipped schema validation.")
        return report

    try:
        dtd = etree.DTD(str(dtd_file))
        report.dtd_validated = True
        report.dtd_passed = bool(dtd.validate(document))
        if not report.dtd_passed:
            for entry in dtd.error_log.filter_from_errors():
                errors.append(str(entry))
            report.errors = errors[:64]
    except etree.DTDParseError as exc:
        report.warnings.append(f"Could not load DTD: {exc}")

    return report
