"""Phase 1: layout-aware PDF text extraction and intermediate representation."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["extract_pdf_document"]


def __getattr__(name: str):
    if name == "extract_pdf_document":
        from app.pipeline.phase1.extract import extract_pdf_document as fn

        return fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from app.pipeline.phase1.extract import extract_pdf_document
