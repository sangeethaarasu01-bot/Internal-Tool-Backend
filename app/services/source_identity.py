"""Source PDF identity (extraction-derived) vs template/output metadata."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.docbook_template import parse_docbook_template_file
from app.utils.isbn_selection import select_primary_isbn_from_lists

ISBN_DIGITS_RE = re.compile(r"[^0-9Xx]")


@dataclass(frozen=True)
class SourceIdentityRecord:
    extraction_id: str
    source_pdf_sha256: str | None
    source_filename: str | None
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    publisher_imprint: str | None = None
    publisher_trade_name: str | None = None
    author_blurb: str | None = None
    publisher_addresses: list[dict[str, str | None]] = field(default_factory=list)
    publication_year: int | None = None
    isbn: str | None = None
    isbns: list[str] = field(default_factory=list)
    isbn_roles: list[tuple[str, str]] = field(default_factory=list)
    copyright_holder: str | None = None
    doi: str | None = None
    page_count: int | None = None
    publication_document_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TemplateIdentityRecord:
    template_id: str | None
    template_filename: str | None
    template_format: str | None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    publication_year: str | None = None
    isbns: list[str] = field(default_factory=list)
    doi: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IdentityConflict:
    field: str
    source_value: str | None
    other_value: str | None
    other_kind: str  # template | output


class IdentityMismatchError(ValueError):
    """Raised when source PDF identity conflicts with template or generated XML."""

    def __init__(
        self,
        message: str,
        *,
        extraction_id: str,
        conflicts: list[IdentityConflict],
    ) -> None:
        super().__init__(message)
        self.extraction_id = extraction_id
        self.conflicts = conflicts


def normalize_isbn(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = ISBN_DIGITS_RE.sub("", value.strip())
    if len(cleaned) < 10:
        return None
    if len(cleaned) == 10:
        return cleaned
    if len(cleaned) == 13:
        return cleaned
    return cleaned[-13:] if len(cleaned) > 13 else cleaned


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    lowered = value.lower()
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


def title_overlap_score(left: str | None, right: str | None) -> float:
    a = set(normalize_title(left).split())
    b = set(normalize_title(right).split())
    if not a or not b:
        return 0.0
    stop = {"the", "a", "an", "and", "of", "in", "to", "for", "with", "on"}
    a -= stop
    b -= stop
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def build_source_identity_from_extraction_doc(doc: dict[str, Any]) -> SourceIdentityRecord:
    phase1 = doc.get("phase1") or (doc.get("result") or {}).get("phase1") or {}
    extraction_id = str(doc.get("_id") or doc.get("extraction_id") or "")
    year = phase1.get("publication_year")
    try:
        year_int = int(year) if year is not None else None
    except (TypeError, ValueError):
        year_int = None
    isbns = list(phase1.get("isbns") or [])
    raw_roles = phase1.get("isbn_roles") or []
    isbn_roles: list[tuple[str, str]] = []
    for item in raw_roles:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            isbn_roles.append((str(item[0]), str(item[1])))
    qual_map = {value: role for value, role in isbn_roles}
    primary_isbn = select_primary_isbn_from_lists(
        isbns,
        fallback=phase1.get("isbn"),
        qualifiers={value: qual_map[value] for value in isbns if value in qual_map},
    )
    return SourceIdentityRecord(
        extraction_id=extraction_id,
        source_pdf_sha256=doc.get("source_pdf_sha256"),
        source_filename=doc.get("original_filename") or doc.get("filename"),
        title=phase1.get("title"),
        subtitle=phase1.get("subtitle"),
        authors=list(phase1.get("authors") or []),
        publisher=phase1.get("publisher"),
        publisher_imprint=phase1.get("publisher_imprint"),
        publisher_trade_name=phase1.get("publisher_trade_name"),
        author_blurb=phase1.get("author_blurb"),
        publisher_addresses=list(phase1.get("publisher_addresses") or []),
        publication_year=year_int,
        isbn=primary_isbn,
        isbns=isbns,
        isbn_roles=isbn_roles,
        copyright_holder=phase1.get("copyright_holder"),
        doi=None,
        page_count=doc.get("page_count"),
        publication_document_type=phase1.get("publication_document_type"),
    )


def build_template_identity(
    template: dict[str, Any],
    template_path: str,
) -> TemplateIdentityRecord:
    schema = template.get("template_schema") or {}
    template_format = schema.get("template_format") or schema.get("root_tag")
    record = TemplateIdentityRecord(
        template_id=template.get("template_id"),
        template_filename=template.get("original_filename"),
        template_format=str(template_format) if template_format else None,
    )
    if schema.get("template_format") == "docbook_5_book" or schema.get("root_tag") == "book":
        try:
            parsed = parse_docbook_template_file(template_path)
            meta = parsed.metadata
            record = TemplateIdentityRecord(
                template_id=template.get("template_id"),
                template_filename=template.get("original_filename"),
                template_format="docbook_5_book",
                title=meta.title,
                authors=list(meta.authors),
                publisher=meta.publisher,
                publication_year=meta.copyright_year,
                isbns=[ident.value for ident in meta.isbns if ident.value],
                doi=meta.doi,
            )
        except Exception:
            pass
    return record


def compare_source_to_template(
    source: SourceIdentityRecord,
    template: TemplateIdentityRecord,
) -> list[IdentityConflict]:
    conflicts: list[IdentityConflict] = []

    source_isbn = normalize_isbn(source.isbn)
    template_isbns = [normalize_isbn(v) for v in template.isbns]
    template_isbns = [v for v in template_isbns if v]
    if source_isbn and template_isbns and all(source_isbn != t for t in template_isbns):
        conflicts.append(
            IdentityConflict(
                field="isbn",
                source_value=source.isbn,
                other_value=", ".join(template.isbns),
                other_kind="template",
            )
        )

    if source.title and template.title:
        score = title_overlap_score(source.title, template.title)
        if score < 0.35:
            conflicts.append(
                IdentityConflict(
                    field="title",
                    source_value=source.title,
                    other_value=template.title,
                    other_kind="template",
                )
            )

    if (
        source.publication_year
        and template.publication_year
        and str(source.publication_year) != str(template.publication_year).strip()
    ):
        conflicts.append(
            IdentityConflict(
                field="publication_year",
                source_value=str(source.publication_year),
                other_value=str(template.publication_year),
                other_kind="template",
            )
        )

    return conflicts


def compare_source_to_output_metadata(
    source: SourceIdentityRecord,
    *,
    title: str | None,
    isbns: list[str],
    doi: str | None,
    publisher: str | None,
    publication_year: str | None,
) -> list[IdentityConflict]:
    conflicts: list[IdentityConflict] = []
    source_isbn = normalize_isbn(source.isbn)
    out_isbns = [normalize_isbn(v) for v in isbns if v]
    out_isbns = [v for v in out_isbns if v]
    if source_isbn and out_isbns and all(source_isbn != v for v in out_isbns):
        conflicts.append(
            IdentityConflict(
                field="isbn",
                source_value=source.isbn,
                other_value=", ".join(isbns),
                other_kind="output",
            )
        )
    if source.title and title:
        if title_overlap_score(source.title, title) < 0.35:
            conflicts.append(
                IdentityConflict(
                    field="title",
                    source_value=source.title,
                    other_value=title,
                    other_kind="output",
                )
            )
    if (
        source.publication_year
        and publication_year
        and str(source.publication_year) != str(publication_year).strip()
    ):
        conflicts.append(
            IdentityConflict(
                field="publication_year",
                source_value=str(source.publication_year),
                other_value=publication_year,
                other_kind="output",
            )
        )
    return conflicts
