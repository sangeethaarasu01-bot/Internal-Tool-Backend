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
    return greek_to_latex(cleaned)


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
