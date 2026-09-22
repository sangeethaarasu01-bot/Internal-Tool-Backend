"""Stage 3: match PDF fields to XML schema."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from app.config import settings
from app.llm.client import LLMClient, create_llm_client
from app.models.mapping_plan import MappingEntry, MappingPlan
from app.models.paper import PaperData
from app.models.schema_map import SchemaMap

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(prompt_template: str, **kwargs: str) -> str:
    out = prompt_template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", v)
    return out


def _default_plan(schema: SchemaMap, paper: PaperData) -> MappingPlan:
    mappings: list[MappingEntry] = []
    if paper.title:
        mappings.append(
            MappingEntry(
                xml_xpath="front/article-meta/title-group/article-title",
                xml_tag="article-title",
                pdf_field="title",
                transform="none",
                confidence=0.85,
                reasoning="Heuristic title mapping",
            )
        )
    if paper.abstract:
        mappings.append(
            MappingEntry(
                xml_xpath="front/article-meta/abstract",
                xml_tag="abstract",
                pdf_field="abstract",
                transform="none",
                confidence=0.85,
                reasoning="Heuristic abstract mapping",
            )
        )
    if paper.authors:
        mappings.append(
            MappingEntry(
                xml_xpath="front/article-meta/contrib-group/contrib",
                xml_tag="contrib",
                pdf_field="authors[]",
                transform="loop",
                confidence=0.8,
                reasoning="Heuristic author loop",
            )
        )
    xpaths = {e.xpath for e in schema.elements}
    mappings = [m for m in mappings if any(m.xml_xpath in x or x.endswith(m.xml_tag) for x in xpaths) or True]
    return MappingPlan(mappings=mappings, llm_model="heuristic")


class SemanticMatcher:
    def __init__(self, llm: LLMClient | None = None) -> None:
        base = llm or create_llm_client()
        self.llm = base.with_model(settings.LLM_MODEL_MATCHING)

    async def match(
        self,
        schema: SchemaMap,
        paper: PaperData,
        on_event: Callable[[dict], None] | None = None,
    ) -> MappingPlan:
        system = _load_prompt("system.txt")
        prompt = _render(
            _load_prompt("semantic_matcher.txt"),
            schema_map=schema.model_dump_json()[:40000],
            paper_data=paper.model_dump_json()[:40000],
        )
        resp = await self.llm.complete(system=system, user=prompt, json_mode=True)
        try:
            data = json.loads(resp.text)
            plan = MappingPlan(
                **data,
                llm_model=resp.model,
                llm_cost_usd=resp.cost_usd,
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            plan = _default_plan(schema, paper)
            plan.llm_model = resp.model
            plan.llm_cost_usd = resp.cost_usd

        known = {e.xpath for e in schema.elements}

        def _matches(m: MappingEntry) -> bool:
            if m.xml_xpath in known:
                return True
            return any(
                x.endswith("/" + m.xml_tag)
                or x.endswith(m.xml_xpath)
                or m.xml_xpath in x
                or m.xml_tag in x
                for x in known
            )

        plan.mappings = [m for m in plan.mappings if _matches(m)]
        if not plan.mappings:
            plan = _default_plan(schema, paper)
            plan.llm_model = resp.model
            plan.llm_cost_usd = resp.cost_usd
        if on_event:
            on_event({"type": "log", "message": f"Mapping plan: {len(plan.mappings)} entries"})
        return plan
