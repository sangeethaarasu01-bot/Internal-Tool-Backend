"""Parse reference strings via LLM."""

from __future__ import annotations

import json
from pathlib import Path

from app.llm.client import LLMClient
from app.models.paper import Reference

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(template: str, **kwargs: str) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", v)
    return out


class ReferenceParser:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def parse(
        self,
        raw_refs: list[str],
        template_examples: list[str] | None = None,
    ) -> list[Reference]:
        examples = "\n".join(template_examples or ["<mixed-citation>"])
        system = _load_prompt("system.txt")
        results: list[Reference] = []
        batch_size = 5
        for i in range(0, len(raw_refs), batch_size):
            batch = raw_refs[i : i + batch_size]
            for j, raw in enumerate(batch):
                num = i + j + 1
                prompt = _render(
                    _load_prompt("reference_extraction.txt"),
                    examples=examples,
                    number=str(num),
                    raw_text=raw,
                )
                resp = await self.llm.complete(system=system, user=prompt, json_mode=True)
                try:
                    parsed = json.loads(resp.text)
                except json.JSONDecodeError:
                    parsed = None
                results.append(
                    Reference(id=f"ref{num}", number=num, raw_text=raw, parsed=parsed)
                )
        return results
