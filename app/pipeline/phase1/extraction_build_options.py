"""Options for Phase 1 document build (tables/figures performance)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

PageProgressCallback = Callable[[int, int, str], None]


@dataclass
class ExtractionBuildOptions:
    skip_tables_figures: bool = False
    """When True, skip table enrichment and figure image extraction entirely."""

    fast_tables_figures: bool = False
    """PyMuPDF-only tables; no camelot/pdfplumber whole-doc passes; optional figure metadata without PNG render."""

    table_page_timeout_sec: float = 5.0
    figure_page_timeout_sec: float = 10.0
    page_progress: PageProgressCallback | None = None
    step4_deadline: float | None = None
    """monotonic() time after which Step 4 should finish with partial/light results."""

    partial_step4: bool = field(default=False, init=False)

    def step4_timed_out(self) -> bool:
        if self.step4_deadline is None:
            return False
        import time

        return time.monotonic() >= self.step4_deadline
