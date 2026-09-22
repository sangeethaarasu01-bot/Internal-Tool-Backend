"""Refine completed job output from user chat instructions."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from lxml import etree
from pydantic import BaseModel, Field

from app.agent.validator import Validator
from app.db import get_job
from app.llm.client import create_llm_client
from app.models.schema_map import SchemaMap
from app.utils.xml_helpers import apply_ieee_entities_to_tree, post_process_ieee_entities

router = APIRouter(prefix="/jobs", tags=["refine"])


class RefineRequest(BaseModel):
    instruction: str = Field(
        default="Apply IEEE hex XML entities for special characters.",
        description="User fix request",
    )
    apply_entities: bool = True


@router.post("/{job_id}/refine")
async def refine_job_output(job_id: str, body: RefineRequest) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(400, "No output XML to refine")

    path = Path(job.output_path)
    xml = path.read_text(encoding="utf-8", errors="replace")

    if body.apply_entities or "entity" in body.instruction.lower() or "special" in body.instruction.lower():
        parser = etree.XMLParser(remove_blank_text=False, recover=True)
        root = etree.fromstring(xml.encode("utf-8"), parser=parser)
        apply_ieee_entities_to_tree(root)
        xml = post_process_ieee_entities(
            etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True).decode("utf-8")
        )

    instruction = body.instruction.strip()
    if instruction and instruction.lower() not in ("fix entities", "apply entities", "fix special characters"):
        llm = create_llm_client()
        system_path = Path(__file__).resolve().parent.parent / "prompts" / "system.txt"
        heal_path = Path(__file__).resolve().parent.parent / "prompts" / "self_heal.txt"
        system = system_path.read_text(encoding="utf-8")
        user = (
            heal_path.read_text(encoding="utf-8").replace("{errors}", instruction)
            + "\n\nCURRENT XML:\n"
            + xml[:80000]
            + "\n\nUser request:\n"
            + instruction
        )
        resp = await llm.complete(system=system, user=user, max_tokens=16000, temperature=0.0)
        candidate = resp.text.strip()
        if candidate.startswith("```"):
            import re

            candidate = re.sub(r"^```(?:xml)?\n?", "", candidate)
            candidate = re.sub(r"\n?```$", "", candidate)
        try:
            etree.fromstring(candidate.encode("utf-8"))
            xml = candidate
        except etree.XMLSyntaxError:
            pass

    path.write_text(xml, encoding="utf-8")

    validation = {"valid": True, "errors": []}
    if job.schema_map_path and Path(job.schema_map_path).exists():
        try:
            schema = SchemaMap(**json.loads(Path(job.schema_map_path).read_text(encoding="utf-8")))
            template_xml = Path(job.template_path).read_text(encoding="utf-8", errors="replace")
            ok, errors = Validator().validate(xml, template_xml, schema)
            validation = {"valid": ok, "errors": errors}
        except Exception as exc:
            validation = {"valid": False, "errors": [str(exc)]}

    return {
        "job_id": job_id,
        "xml_content": xml,
        "validation": validation,
        "download_url": f"/api/download/{job_id}",
    }
