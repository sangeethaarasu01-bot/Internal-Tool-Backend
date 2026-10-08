"""Generic academic PDF table extraction.

Camelot → img2table → PyMuPDF → RapidFuzz (captions) → pdfplumber fallback.
"""

from app.pipeline.table_extraction.pipeline import print_validation_report, run_extraction, write_output

__all__ = ["run_extraction", "write_output", "print_validation_report"]
