"""Strip illegal XML characters from PDF-derived PaperData strings."""

from __future__ import annotations

from app.models.paper import Author, PaperData, Reference, Section
from app.utils.xml_text import sanitize_xml_text


def _s(value: str) -> str:
    return sanitize_xml_text(value) if value else value


def sanitize_paper_data(paper: PaperData) -> PaperData:
    """Remove NULL bytes and XML-illegal control chars from extracted PDF text."""
    authors = [
        a.model_copy(
            update={
                "first_name": _s(a.first_name),
                "last_name": _s(a.last_name),
                "full_name": _s(a.full_name),
                "orcid": _s(a.orcid) if a.orcid else a.orcid,
                "email": _s(a.email) if a.email else a.email,
                "bio": _s(a.bio) if a.bio else a.bio,
            }
        )
        for a in paper.authors
    ]

    def _section(sec: Section) -> Section:
        return sec.model_copy(
            update={
                "label": _s(sec.label) if sec.label else sec.label,
                "title": _s(sec.title),
                "paragraphs": [_s(p) for p in sec.paragraphs],
                "subsections": [_section(sub) for sub in sec.subsections],
            }
        )

    return paper.model_copy(
        update={
            "title": _s(paper.title),
            "abstract": _s(paper.abstract),
            "keywords": [_s(k) for k in paper.keywords],
            "authors": authors,
            "sections": [_section(s) for s in paper.sections],
            "references": [
                r.model_copy(update={"raw_text": _s(r.raw_text)}) for r in paper.references
            ],
        }
    )
