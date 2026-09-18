"""Layout processing package."""

from __future__ import annotations

from typing import Any

__all__ = ["build_full_extraction_result", "process_document_structure"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.services.layout.document_pipeline import (
            build_full_extraction_result,
            process_document_structure,
        )

        return {
            "build_full_extraction_result": build_full_extraction_result,
            "process_document_structure": process_document_structure,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
