"""Job listing and results."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.agent.validator import Validator
from app.db import get_job, list_jobs, update_job
from app.models.mapping_plan import MappingPlan
from app.models.schema_map import SchemaMap

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def api_list_jobs() -> list[dict]:
    jobs = list_jobs()
    return [j.model_dump() for j in jobs]


@router.get("/jobs/{job_id}")
def api_get_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.model_dump()


@router.get("/result/{job_id}")
def api_get_result(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    xml_content = ""
    validation = {"valid": False, "errors": []}
    if job.output_path and Path(job.output_path).exists():
        xml_content = Path(job.output_path).read_text(encoding="utf-8", errors="replace")
        if job.schema_map_path and Path(job.schema_map_path).exists():
            try:
                schema = SchemaMap(
                    **json.loads(Path(job.schema_map_path).read_text(encoding="utf-8"))
                )
                template_xml = Path(job.template_path).read_text(
                    encoding="utf-8", errors="replace"
                )
                ok, errors = Validator().validate(xml_content, template_xml, schema)
                validation = {"valid": ok, "errors": errors}
            except Exception as exc:
                validation = {
                    "valid": False,
                    "errors": [f"Validation skipped: {exc}"],
                }
    return {
        "status": job.status,
        "xml_content": xml_content,
        "validation": validation,
        "cost": job.llm_cost_usd,
        "tokens": job.llm_tokens,
        "error": job.error,
        "output_path": job.output_path,
        "download_url": f"/api/download/{job_id}",
    }


@router.get("/download/{job_id}")
def api_download(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job or not job.output_path:
        raise HTTPException(404, "Output not found")
    path = Path(job.output_path)
    if not path.exists():
        raise HTTPException(404, "Output file missing")
    return FileResponse(path, filename=f"{job_id}.xml", media_type="application/xml")


@router.delete("/jobs/{job_id}")
def api_delete_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    update_job(job_id, status="deleted")
    return {"deleted": True}
