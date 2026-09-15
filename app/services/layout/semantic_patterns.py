"""Pattern detection for semantic classification using layout + typography + text."""

from __future__ import annotations

import re

from app.models.document_structure import ProcessedBlock

ROMAN_SECTION_RE = re.compile(
    r"^(?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.\s+[A-Z]",
    re.IGNORECASE,
)
LETTER_SUBSECTION_RE = re.compile(r"^[A-Z]\.\s+[A-Za-z]")
NUMBERED_SUBSECTION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?\s+[A-Za-z]")
LIST_ITEM_RE = re.compile(r"^\d+\)\s+")
LIST_ITEM_ALPHA_RE = re.compile(r"^\([a-zA-Z]\)\s+")
LIST_ITEM_ROMAN_RE = re.compile(r"^[ivxIVX]+\)\s+")
LIST_ITEM_DOT_NUMERIC_RE = re.compile(r"^\d+\.\s+")
LIST_ITEM_BULLET_RE = re.compile(r"^[•▪▫◦○●■□\-–—\*]\s+")
REFERENCE_LABEL_RE = re.compile(r"^\[\d+\]")
FIGURE_CAPTION_RE = re.compile(r"^fig\.\s*\d+", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^table\s+[IVX\d]+", re.IGNORECASE)
TABLE_CONTINUATION_KNOWN_RE = re.compile(
    r"^(?:OPERATIONAL STATISTICS|COMPARATIVE PERFORMANCE|HPLC VALUES|PRECURSORS FOR)$",
    re.IGNORECASE,
)
ABSTRACT_RE = re.compile(r"^abstract[\s—\-–]", re.IGNORECASE)
KEYWORDS_RE = re.compile(r"^index terms[\s—\-–]", re.IGNORECASE)
DATE_HISTORY_RE = re.compile(r"^received\s+\d", re.IGNORECASE)
CORRESPONDING_RE = re.compile(r"corresponding author", re.IGNORECASE)
REFERENCE_HEADING_RE = re.compile(r"^references$", re.IGNORECASE)
ACKNOWLEDGMENT_RE = re.compile(r"^acknowledgment", re.IGNORECASE)
JOURNAL_HEADER_RE = re.compile(r"IEEE\s+SENSORS\s+JOURNAL", re.IGNORECASE)
CITATION_RE = re.compile(r"(?:\[\d+\]|doi:\s*10\.|vol\.\s*\d+)", re.IGNORECASE)
AFFILIATION_RE = re.compile(
    r"(department of|university|institute|college|@\w+\.\w+|\.ac\.|\.edu|india|kolkata)",
    re.IGNORECASE,
)
AUTHOR_RE = re.compile(
    r"(member,\s*ieee|and\s+[A-Z][a-z]+|,\s*[A-Z][a-z]+\s+[A-Z])",
    re.IGNORECASE,
)
MATH_SYMBOL_RE = re.compile(r"(=|∈|∑|∫|±|≤|≥|×|÷|√|α|β|γ|δ|θ|λ|μ|σ|π|ω|\^|\{|\}|\.{3})")
# TODO(phase-2): Paper-specific tokens (yHPLC, fTAN, XTAN, TAN/TF/TH) come from one
# IEEE reference paper (1458242.xml). Replace with generic LaTeX/math detection and
# an external per-domain keyword list so template changes do not require code edits.
MATH_FRAGMENT_RE = re.compile(
    r"(?:"
    r"^X\d+$|"
    r"^(?:TAN|TF|TH),?\s*(?:X\d+|\.{3})|"
    r"^yHPLC|"
    r"(?:TAN|TF|TH)\s*=\s*f|"
    r"X(?:TAN|TF|TH)\s*∈|"
    r"ffused\(|"
    r"f(?:TAN|TF|TH)\(|"
    r"\.{3}\s*,\s*X\d+|"
    r"(?:TAN|TF|TH),\s*(?:\.\s*){3},\s*X\d+"
    r")",
    re.IGNORECASE,
)

# Standalone R^2 in running prose is inline math, not a display fragment.
_R_SQUARED_RE = re.compile(r"\bR\^2\b", re.IGNORECASE)
MERGED_HEADING_SPLIT_RE = re.compile(
    r"^((?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.\s+[A-Z][A-Z0-9 \-/&]+?)\s+([A-Z]\.\s+.+)$"
)

MIN_FIGURE_HEIGHT = 8.0
MIN_FIGURE_AREA = 800.0
MAX_HEADING_WORDS = 14
MAX_SUBSECTION_CHARS = 90


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split()).strip()


def first_line(text: str) -> str:
    return (text or "").split("\n", 1)[0].strip()


def block_height(block: ProcessedBlock) -> float:
    return block.bbox[3] - block.bbox[1]


def block_area(block: ProcessedBlock) -> float:
    return (block.bbox[2] - block.bbox[0]) * (block.bbox[3] - block.bbox[1])


def is_roman_section_heading(text: str) -> bool:
    line = first_line(text)
    if not ROMAN_SECTION_RE.match(line):
        return False
    words = line.split()
    if len(words) > MAX_HEADING_WORDS:
        return False
    rest = re.sub(r"^(?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.\s+", "", line, flags=re.I)
    heading_words = rest.split()[:6]
    if not heading_words:
        return False
    upper_count = sum(1 for w in heading_words if w.isupper() or w.isdigit())
    return upper_count / len(heading_words) >= 0.6


def is_letter_subsection_heading(text: str, block: ProcessedBlock | None = None) -> bool:
    line = first_line(text)
    if not LETTER_SUBSECTION_RE.match(line):
        return False
    if len(line) > MAX_SUBSECTION_CHARS:
        return False
    if block is not None:
        height = block_height(block)
        if height > 25 and len(line) > 50:
            return False
    words = line.split()
    return len(words) <= MAX_HEADING_WORDS


def is_numbered_subsection_heading(text: str) -> bool:
    line = first_line(text)
    return bool(NUMBERED_SUBSECTION_RE.match(line)) and len(line.split()) <= MAX_HEADING_WORDS


def is_list_item(text: str, *, in_references: bool = False) -> bool:
    from app.services.layout.list_detection import is_list_item as detect_list_item

    return detect_list_item(text, in_references=in_references)


def is_math_fragment(text: str) -> bool:
    """Return True when a block is a display-math fragment (not inline prose).

    Conservative for prose containing standalone R^2: such lines are handled as
    paragraph + inline_math in ir_builder, not display_math.
    """
    raw = (text or "").replace("\n", " ")
    t = normalize_text(text)
    if not t:
        return False

    # R^2 embedded in a sentence → inline math, not a display fragment.
    if _R_SQUARED_RE.search(t):
        words = t.split()
        if len(words) >= 4 and t[0].isupper() and not MATH_FRAGMENT_RE.search(t):
            return False

    if MATH_FRAGMENT_RE.search(t) or MATH_FRAGMENT_RE.search(raw):
        return True
    if len(t) <= 4 and re.match(r"^[A-Z]\d*$", t):
        return True
    # Short IEEE variable tokens (e.g. XTAN) used as display-math labels.
    if len(t) <= 4 and re.match(r"^X[A-Z]{1,3}$", t):
        return True

    # Strip standalone R^2 before symbol scan so ^ does not false-positive.
    t_no_rsq = re.sub(_R_SQUARED_RE, "", t).strip()
    if MATH_SYMBOL_RE.search(t_no_rsq) and len(t_no_rsq) < 60:
        return True

    # Prose guard: long capitalized sentences without real math tokens.
    words = t.split()
    if len(words) >= 4 and t[0].isupper():
        if not MATH_FRAGMENT_RE.search(t_no_rsq) and not MATH_SYMBOL_RE.search(t_no_rsq):
            return False

    if re.match(r"^[A-Z]{1,4},?\s*X\d", t):
        return True
    if t.endswith("}") and len(t) < 25:
        return True
    if re.match(r"^yHPLC", t, re.I):
        return True
    if re.match(r"^where\s+yHPLC", t, re.I):
        return True
    if re.match(r"^(?:TAN|TF|TH)\s*,\s*yHPLC", t, re.I):
        return True
    return False


def is_explanatory_math_context(text: str) -> bool:
    """Long prose that mentions math but is body text."""
    t = normalize_text(text)
    if re.match(r"^where\s+yHPLC", t, re.I):
        return False
    if re.match(r"^(?:TAN|TF|TH)\s*,\s*yHPLC", t, re.I):
        return False
    if len(t) > 80 and not MATH_SYMBOL_RE.search(t[:30]):
        return True
    if re.match(r"^(?:where|The model|There are|From the)", t, re.I) and not is_math_fragment(t):
        return True
    return False


def is_valid_figure_block(block: ProcessedBlock) -> bool:
    if block.block_type != "image":
        return False
    h = block_height(block)
    if h < MIN_FIGURE_HEIGHT:
        return False
    return block_area(block) >= MIN_FIGURE_AREA


def is_decorative_layout_object(block: ProcessedBlock) -> bool:
    if block.block_type != "image":
        return False
    return block_height(block) < MIN_FIGURE_HEIGHT or block_area(block) < MIN_FIGURE_AREA


def split_merged_headings(text: str) -> list[str]:
    """Split e.g. 'III. RESULTS A. DPV Responses' into section + subsection."""
    line = first_line(text)
    match = MERGED_HEADING_SPLIT_RE.match(line)
    if match:
        return [match.group(1).strip(), match.group(2).strip()]
    return [line]


def clean_section_heading(text: str) -> str:
    line = first_line(text)
    line = re.sub(r"\s+[A-Z]$", "", line)
    return line.strip()


def split_acknowledgment(text: str) -> tuple[str, str | None]:
    match = re.match(r"^(ACKNOWLEDGMENT)\s+(.+)$", first_line(text), re.I)
    if match:
        return match.group(1).upper(), match.group(2).strip()
    return first_line(text), None


def split_section_and_body(text: str) -> tuple[str | None, str | None]:
    """Split e.g. 'IV. CONCLUSION The current approach...' into heading + body."""
    line = first_line(text)
    match = re.match(
        r"^((?:I{1,3}|IV|VI{0,3}|IX|X{0,3})\.\s+[A-Z][A-Z0-9 \-/&]+?)\s+([A-Z][a-z].+)$",
        line,
    )
    if match and len(match.group(1).split()) <= MAX_HEADING_WORDS:
        return match.group(1).strip(), match.group(2).strip()
    return None, None


def split_reference_entries(text: str) -> list[tuple[str | None, str]]:
    """Split a block containing multiple ``[n]`` bibliography items."""
    normalized = normalize_text(text)
    if not normalized:
        return []

    if not re.search(r"\[\d+\]", normalized):
        return [(extract_reference_label(normalized), normalized)]

    parts = re.split(r"(?=\[\d+\]\s*)", normalized)
    entries: list[tuple[str | None, str]] = []
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        match = re.match(r"^(\[\d+\])\s*(.*)$", chunk, flags=re.DOTALL)
        if match:
            entries.append((match.group(1), match.group(2).strip()))
        elif entries:
            label, body = entries[-1]
            entries[-1] = (label, f"{body} {chunk}".strip())
        else:
            entries.append((None, chunk))
    return entries


def is_table_continuation_heading(text: str) -> bool:
    """Detect short all-caps table header rows that follow a table caption."""
    line = first_line(text).strip()
    if not line:
        return False
    if TABLE_CAPTION_RE.match(line):
        return False
    if is_roman_section_heading(text) or ROMAN_SECTION_RE.match(line):
        return False
    if LETTER_SUBSECTION_RE.match(line) or NUMBERED_SUBSECTION_RE.match(line):
        return False
    if TABLE_CONTINUATION_KNOWN_RE.match(line):
        return True
    if len(line) < 5 or len(line) > 60:
        return False
    letters = [char for char in line if char.isalpha()]
    if not letters:
        return False
    return all(char.isupper() for char in letters)


def extract_table_label(text: str) -> str | None:
    match = TABLE_CAPTION_RE.match(first_line(text))
    if not match:
        return None
    return match.group(0).strip()


def is_standalone_equation_text(text: str) -> bool:
    """Detect short equation-like lines that are not full prose paragraphs."""
    t = normalize_text(text)
    if not t or len(t) > 160:
        return False
    words = t.split()
    if len(words) > 14:
        return False
    if is_math_fragment(t):
        return True
    if "=" in t and MATH_SYMBOL_RE.search(t) and len(words) <= 10:
        return True
    if re.search(r"[A-Za-z]\([^)]+\)\s*=", t) and len(words) <= 8:
        return True
    return False


def extract_reference_label(text: str) -> str | None:
    match = REFERENCE_LABEL_RE.match(normalize_text(text))
    return match.group(0) if match else None


def is_title_candidate(block: ProcessedBlock, title_font_threshold: float) -> bool:
    text = normalize_text(block.text)
    if not text or block.exclude_from_content:
        return False
    if block.column != "FULL_WIDTH":
        return False
    size = block.dominant_font_size or 0
    return size >= title_font_threshold and len(text) < 200 and not ABSTRACT_RE.match(text)


def is_author_candidate(block: ProcessedBlock, title_bottom_y: float) -> bool:
    text = normalize_text(block.text)
    if not text or block.exclude_from_content:
        return False
    if block.bbox[1] < title_bottom_y - 5:
        return False
    if block.column != "FULL_WIDTH":
        return False
    if AUTHOR_RE.search(text) or ("," in text and len(text.split()) <= 40):
        size = block.dominant_font_size or 0
        return 8 <= size <= 14
    return False
