"""Constants for the intermediate representation (IR) schema.

All IR type strings and JATS tag mappings live here to avoid magic strings
scattered across the codebase.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Inline element types (composable content inside block-level nodes)
# ---------------------------------------------------------------------------

IR_INLINE_TEXT: Final[str] = "text"
IR_INLINE_MATH: Final[str] = "inline_math"

# ---------------------------------------------------------------------------
# Block-level IR node types
# ---------------------------------------------------------------------------

IR_PARAGRAPH: Final[str] = "paragraph"
IR_HEADING: Final[str] = "heading"
IR_DISPLAY_MATH: Final[str] = "display_math"
IR_FIGURE: Final[str] = "figure"
IR_TABLE: Final[str] = "table"
IR_REFERENCE: Final[str] = "reference"
IR_LIST: Final[str] = "list"
IR_LIST_ITEM: Final[str] = "list_item"

# Front / back matter node types
IR_DOCUMENT: Final[str] = "document"
IR_JOURNAL_HEADER: Final[str] = "journal_header"
IR_TITLE: Final[str] = "title"
IR_AUTHOR: Final[str] = "author"
IR_AFFILIATION: Final[str] = "affiliation"
IR_CORRESPONDING_AUTHOR: Final[str] = "corresponding_author"
IR_DATE_HISTORY: Final[str] = "date_history"
IR_ABSTRACT: Final[str] = "abstract"
IR_KEYWORDS: Final[str] = "keywords"
IR_FIGURE_CAPTION: Final[str] = "figure_caption"
IR_TABLE_CAPTION: Final[str] = "table_caption"
IR_REFERENCE_LIST: Final[str] = "reference_list"
IR_FOOTER: Final[str] = "footer"
IR_PAGE_NUMBER: Final[str] = "page_number"
IR_RUNNING_HEADER: Final[str] = "running_header"
IR_LAYOUT_OBJECT: Final[str] = "layout_object"
IR_UNKNOWN: Final[str] = "unknown"

# ---------------------------------------------------------------------------
# Legacy semantic classification labels (uppercase) → IR node types
# ---------------------------------------------------------------------------

SEMANTIC_TO_IR_TYPE: Final[dict[str, str]] = {
    "DOCUMENT": IR_DOCUMENT,
    "JOURNAL_HEADER": IR_JOURNAL_HEADER,
    "TITLE": IR_TITLE,
    "AUTHOR": IR_AUTHOR,
    "AFFILIATION": IR_AFFILIATION,
    "CORRESPONDING_AUTHOR": IR_CORRESPONDING_AUTHOR,
    "DATE_HISTORY": IR_DATE_HISTORY,
    "ABSTRACT": IR_ABSTRACT,
    "KEYWORDS": IR_KEYWORDS,
    "SECTION": IR_HEADING,
    "SUBSECTION": IR_HEADING,
    "PARAGRAPH": IR_PARAGRAPH,
    "FIGURE": IR_FIGURE,
    "FIGURE_CAPTION": IR_FIGURE_CAPTION,
    "TABLE": IR_TABLE,
    "TABLE_CAPTION": IR_TABLE_CAPTION,
    "EQUATION": IR_DISPLAY_MATH,
    "LIST": IR_LIST,
    "LIST_ITEM": IR_LIST_ITEM,
    "REFERENCE": IR_REFERENCE,
    "REFERENCE_LIST": IR_REFERENCE_LIST,
    "FOOTER": IR_FOOTER,
    "PAGE_NUMBER": IR_PAGE_NUMBER,
    "RUNNING_HEADER": IR_RUNNING_HEADER,
    "LAYOUT_OBJECT": IR_LAYOUT_OBJECT,
    "UNKNOWN_TEXT": IR_UNKNOWN,
}

# ---------------------------------------------------------------------------
# IR node type → JATS tag (per client spec + IEEE extensions)
# ---------------------------------------------------------------------------

IR_TYPE_TO_JATS_TAG: Final[dict[str, str]] = {
    IR_PARAGRAPH: "p",
    IR_HEADING: "title",
    IR_DISPLAY_MATH: "disp-formula",
    IR_INLINE_MATH: "inline-formula",
    IR_FIGURE: "fig",
    IR_TABLE: "table-wrap",
    IR_REFERENCE: "ref",
    IR_LIST: "list",
    IR_LIST_ITEM: "list-item",
    IR_DOCUMENT: "article",
    IR_JOURNAL_HEADER: "journal-header",
    IR_TITLE: "article-title",
    IR_AUTHOR: "contrib",
    IR_AFFILIATION: "aff",
    IR_CORRESPONDING_AUTHOR: "corresp",
    IR_DATE_HISTORY: "date-history",
    IR_ABSTRACT: "abstract",
    IR_KEYWORDS: "kwd-group",
    IR_FIGURE_CAPTION: "caption",
    IR_TABLE_CAPTION: "caption",
    IR_REFERENCE_LIST: "ref-list",
    IR_FOOTER: "footer",
    IR_PAGE_NUMBER: "page-number",
    IR_RUNNING_HEADER: "running-header",
    IR_LAYOUT_OBJECT: "layout-object",
    IR_UNKNOWN: "unknown",
}
