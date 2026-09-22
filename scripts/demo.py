"""End-to-end demo using sample PDF + XML template."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.converter_agent import ConverterAgent
from app.agent.validator import Validator
from app.config import settings
from app.llm.client import create_llm_client
from app.models.mapping_plan import MappingPlan
from app.models.schema_map import SchemaMap

SAMPLE_PDF = settings.DATA_DIR / "samples" / "access-khan-3639184-proof1.pdf"
SAMPLE_XML = settings.DATA_DIR / "samples" / "1458251.xml"
OUT = settings.DATA_DIR / "outputs" / "demo_output.xml"


def ensure_pdf() -> None:
    if not SAMPLE_PDF.exists():
        from scripts.generate_sample_pdf import main

        main()


async def main() -> None:
    ensure_pdf()
    job_id = "demo"
    events: list[dict] = []

    def on_event(e: dict) -> None:
        events.append(e)
        print(f"[{e.get('type')}] {e.get('message', '')} {e.get('progress', '')}")

    agent = ConverterAgent(create_llm_client(), on_event=on_event)
    result = await agent.run(SAMPLE_PDF, SAMPLE_XML, job_id)
    OUT.write_text(Path(result["output_path"]).read_text(encoding="utf-8"), encoding="utf-8")

    schema = SchemaMap(**json.loads(Path(result["schema_map_path"]).read_text()))
    plan = MappingPlan(**json.loads(Path(result["mapping_plan_path"]).read_text()))
    template_xml = SAMPLE_XML.read_text(encoding="utf-8")
    ok, errors = Validator().validate(OUT.read_text(encoding="utf-8"), template_xml, schema)

    print("\n=== Schema Map ===")
    print(f"root_tag={schema.root_tag} elements={len(schema.elements)}")
    print("\n=== Mapping Plan ===")
    print(f"mappings={len(plan.mappings)} unmapped_xml={len(plan.unmapped_xml)}")
    print("\n=== Output ===")
    print(f"written: {OUT}")
    print(f"validation: {'OK' if ok else errors}")
    print(f"LLM cost (USD): {result['cost_usd']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
