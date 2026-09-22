"""Convert raw equation text to LaTeX via LLM."""

from __future__ import annotations

from pathlib import Path

from app.llm.client import LLMClient
from app.models.paper import Equation, PaperData

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(template: str, **kwargs: str) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", v)
    return out


class EquationHandler:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def process(self, paper: PaperData, jats: bool = False) -> PaperData:
        system = _load_prompt("system.txt")
        updated: list[Equation] = []
        for eq in paper.equations:
            prompt = _render(_load_prompt("equation_extraction.txt"), raw=eq.latex)
            resp = await self.llm.complete(system=system, user=prompt, max_tokens=2000)
            latex = resp.text.strip()
            if jats:
                latex = (
                    f'<disp-formula id="{eq.id}"><tex-math notation="LaTeX">'
                    f"\\begin{{equation*}}{latex}\\tag{{{eq.number}}}\\end{{equation*}}"
                    f"</tex-math></disp-formula>"
                )
            updated.append(Equation(id=eq.id, number=eq.number, latex=latex, display=eq.display))
        paper.equations = updated
        return paper
