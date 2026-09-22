"""Schema map API."""

import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
import shutil
from uuid import uuid4

from app.agent.schema_analyzer import SchemaAnalyzer
from app.config import settings
from app.db import Client, get_job, get_session
from app.llm.client import create_llm_client

router = APIRouter(prefix="/schema", tags=["schema"])


@router.get("/{client_id}")
def get_schema_for_client(client_id: str) -> dict:
    with get_session() as session:
        client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    if client.schema_map_path and Path(client.schema_map_path).exists():
        return json.loads(Path(client.schema_map_path).read_text(encoding="utf-8"))
    cached = settings.schemas_dir / f"{client.template_hash}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    raise HTTPException(404, "Schema not analyzed yet")


@router.get("/job/{job_id}")
def get_schema_for_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    out: dict = {}
    if job.schema_map_path and Path(job.schema_map_path).exists():
        out["schema_map"] = json.loads(Path(job.schema_map_path).read_text(encoding="utf-8"))
    if job.mapping_plan_path and Path(job.mapping_plan_path).exists():
        out["mapping_plan"] = json.loads(Path(job.mapping_plan_path).read_text(encoding="utf-8"))
    if not out:
        raise HTTPException(404, "Schema artifacts not ready")
    return out


@router.post("/analyze")
async def analyze_template(template: UploadFile = File(...)) -> dict:
    if not template.filename or not template.filename.lower().endswith(".xml"):
        raise HTTPException(400, "template must be .xml")
    tmp = settings.uploads_dir / f"adhoc_{uuid4()}.xml"
    with tmp.open("wb") as f:
        shutil.copyfileobj(template.file, f)
    schema = await SchemaAnalyzer(create_llm_client()).analyze(tmp)
    return json.loads(schema.model_dump_json())
