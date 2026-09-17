"""Normalize extracted math text to LaTeX and extract equation labels."""

from __future__ import annotations

import re

from app.utils.text_utils import normalize_text

_GREEK_TO_LATEX = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\epsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\phi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Α": r"A",
    "Β": r"B",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
}

_EQUATION_LABEL_RE = re.compile(
    r"^(?P<body>.+?)\s*(?P<label>\((?:\d+|[ivxIVX]+)\))\s*$"
)
_PROSE_IN_EQUATION_RE = re.compile(
    r"(samples|total of|fused data|table\s+[IVX\d]+)",
    re.IGNORECASE,
)
_DISPLAY_EQUATION_RE = re.compile(
    r"(=|∈|∑|∫|±|≤|≥|×|÷|√|\^|\{|\}|\\[a-zA-Z]+|f[A-Z]{2,}\()",
)
_GREEK_COMMAND_SUBSCRIPT_RE = re.compile(
    r"(\\(?:alpha|beta|gamma|delta|epsilon|theta|lambda|mu|omega|phi|psi|sigma|chi|upsilon))([a-zA-Z0-9])"
)
_SINGLE_BRACE_SUBSCRIPT_RE = re.compile(r"([A-Za-z])\{([a-zA-Z0-9])\}")
_UNBRACED_SUBSCRIPT_RE = re.compile(r"([A-Za-z])_([a-zA-Z0-9])")
_UNBRACED_SUPERSCRIPT_RE = re.compile(r"\^(\d+|[a-zA-Z])")


def is_greek_character(char: str) -> bool:
    return len(char) == 1 and char in _GREEK_TO_LATEX


def greek_to_latex(text: str) -> str:
    if not text:
        return ""
    parts: list[str] = []
    for char in text:
        parts.append(_GREEK_TO_LATEX.get(char, char))
    return "".join(parts)


def normalize_display_latex(text: str) -> str:
    """Normalize display-equation text for ``<tex-math>`` output."""
    cleaned = normalize_text(text)
    cleaned = cleaned.replace(" . . . ", " \\ldots ")
    cleaned = re.sub(r"\s*∈\s*", r" \\in ", cleaned)
    return apply_latex_subscripts_superscripts(greek_to_latex(cleaned))


def equation_number_from_label(label: str | None) -> str | None:
    if not label:
        return None
    match = re.search(r"(\d+)", label)
    return match.group(1) if match else None


def display_formula_id(label: str | None, template_ids: dict[str, str] | None = None) -> str | None:
    """Return IEEE ``deqn`` id for a numbered display equation."""
    eq_num = equation_number_from_label(label)
    if not eq_num:
        return None
    if template_ids and eq_num in template_ids:
        return template_ids[eq_num]
    return f"deqn{eq_num}"


def apply_latex_subscripts_superscripts(text: str) -> str:
    """Add LaTeX ``_{}`` / ``^{}`` where PDF text omits braces."""
    if not text or "\\begin{" in text:
        return text

    converted = text
    converted = _UNBRACED_SUPERSCRIPT_RE.sub(r"^{\1}", converted)
    converted = _UNBRACED_SUBSCRIPT_RE.sub(r"\1_{\2}", converted)
    converted = _SINGLE_BRACE_SUBSCRIPT_RE.sub(r"\1_{\2}", converted)
    converted = _GREEK_COMMAND_SUBSCRIPT_RE.sub(r"\1 _{\2}", converted)
    return converted


def format_display_math_for_ieee(latex: str, label: str | None = None) -> str:
    """Wrap display math in ``equation*`` and add ``\\tag {n}`` when numbered."""
    body = apply_latex_subscripts_superscripts(latex)
    if "\\begin{equation" in body or "\\begin{align" in body:
        return body

    eq_num = equation_number_from_label(label)
    if eq_num:
        return f"\\begin{{equation*}} {body} \\tag {{{eq_num}}}\\end{{equation*}}"
    return f"\\begin{{equation*}} {body} \\end{{equation*}}"


def format_inline_math_for_ieee(latex: str) -> str:
    """Format inline math for IEEE ``<tex-math>`` (``$...$`` delimiters)."""
    body = apply_latex_subscripts_superscripts(latex).strip()
    if body.startswith("$") and body.endswith("$"):
        return body
    return f"${body}$"


def split_equation_label(text: str) -> tuple[str | None, str]:
    """Return ``(label, body)`` when text ends with ``(1)`` or ``(i)``."""
    normalized = normalize_text(text)
    match = _EQUATION_LABEL_RE.match(normalized)
    if match:
        return match.group("label"), match.group("body").strip()
    return None, normalized


def is_plausible_display_equation(text: str) -> bool:
    """Reject table prose and single-token noise misclassified as equations."""
    normalized = normalize_text(text)
    if not normalized:
        return False
    if re.match(r"^where\b", normalized, flags=re.IGNORECASE):
        return False
    if _PROSE_IN_EQUATION_RE.search(normalized):
        return False
    if len(normalized) <= 2 and re.fullmatch(r"[A-Z]", normalized):
        return False
    if re.fullmatch(r"X\d+", normalized):
        return False
    if re.fullmatch(r"(?:TAN|TF|TH)", normalized, flags=re.IGNORECASE):
        return False
    if re.fullmatch(r"(?:TAN|TF|TH),\s*X\d+", normalized, flags=re.IGNORECASE):
        return False
    if re.fullmatch(r"(?:TAN|TF|TH),\s*(?:\.\s*){3},\s*X\d+", normalized):
        return False
    if "=" in normalized or _DISPLAY_EQUATION_RE.search(normalized):
        return True
    if re.search(r"f[A-Z]{2,}\(", normalized):
        return True
    return len(normalized) >= 6 and _DISPLAY_EQUATION_RE.search(normalized)


def is_equation_group_boundary(previous_text: str, next_text: str) -> bool:
    """Start a new display equation before the next ``yHPLC`` or ``where`` line."""
    previous = normalize_text(previous_text)
    nxt = normalize_text(next_text)
    if re.match(r"^where\b", nxt, flags=re.IGNORECASE):
        return True
    if re.match(r"^X(?:TAN|TF|TH)\s*∈", nxt, flags=re.IGNORECASE):
        return True
    if re.match(r"^yHPLC\b", nxt, flags=re.IGNORECASE) and (
        "=" in previous or re.search(r"f[A-Z]{2,}\(", previous)
    ):
        return True
    return False
