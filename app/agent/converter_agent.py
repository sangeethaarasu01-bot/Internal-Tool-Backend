"""Orchestrator for the 5-stage conversion pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from app.agent.pdf_extractor import PDFExtractor
from app.agent.schema_analyzer import SchemaAnalyzer
from app.agent.semantic_matcher import SemanticMatcher
from app.agent.validator import Validator
from app.agent.xml_generator import XMLGenerator
from app.config import settings
from app.llm.client import LLMClient, create_llm_client


class ConverterAgent:
    def __init__(
        self,
        llm: LLMClient | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.llm = llm or create_llm_client()
        self.on_event = on_event or (lambda _e: None)

    def emit(self, event_type: str, message: str, progress: int | None = None) -> None:
        payload: dict = {"type": event_type, "message": message}
        if progress is not None:
            payload["progress"] = progress
        self.on_event(payload)

    async def run(
        self,
        pdf_path: Path,
        template_path: Path,
        job_id: str,
        client_id: str | None = None,
    ) -> dict:
        self.emit("stage", "starting", 0)

        self.emit("stage", "parsing_template", 10)
        schema_analyzer = SchemaAnalyzer(self.llm)
        schema = await schema_analyzer.analyze(template_path, self.on_event)
        if self.llm.offline_fallback_used:
            self.emit("log", "Running in offline mode — top up Anthropic credits for best results")
        schema_path = settings.schemas_dir / f"{job_id}.json"
        schema_path.write_text(schema.model_dump_json(indent=2), encoding="utf-8")

        self.emit("stage", "extracting_pdf", 30)
        paper = await PDFExtractor(self.llm).extract(pdf_path, self.on_event, job_id=job_id)
        paper_path = settings.outputs_dir / f"{job_id}_paper.json"
        paper_path.write_text(paper.model_dump_json(indent=2), encoding="utf-8")

        self.emit("stage", "matching_semantics", 55)
        plan = await SemanticMatcher(self.llm).match(schema, paper, self.on_event)
        plan_path = settings.outputs_dir / f"{job_id}_plan.json"
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

        self.emit("stage", "generating_xml", 75)
        template_xml = template_path.read_text(encoding="utf-8", errors="replace")
        output_xml = await XMLGenerator(self.llm).generate(
            template_xml, paper, plan, self.on_event
        )

        self.emit("stage", "validating", 92)
        ok, errors = Validator().validate(output_xml, template_xml, schema)

        if not ok:
            for attempt in range(settings.MAX_RETRIES):
                self.emit("log", f"validation failed, retry {attempt + 1}: {errors}")
                output_xml = await XMLGenerator(self.llm).generate(
                    template_xml,
                    paper,
                    plan,
                    self.on_event,
                    prior_errors=errors,
                )
                ok, errors = Validator().validate(output_xml, template_xml, schema)
                if ok:
                    break

        if not ok:
            raise ValueError(f"Validation failed: {errors}")

        output_path = settings.outputs_dir / f"{job_id}.xml"
        output_path.write_text(output_xml, encoding="utf-8")
        self.emit("stage", "done", 100)
        self.emit("done", "Conversion complete", 100)
        return {
            "output_path": str(output_path),
            "schema_map_path": str(schema_path),
            "mapping_plan_path": str(plan_path),
            "cost_usd": self.llm.total_cost,
            "tokens": self.llm.total_tokens,
        }
