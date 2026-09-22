"""Start conversion job."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.agent.converter_agent import ConverterAgent
from app.db import get_job, update_job
from app.llm.client import create_llm_client
from app.events import ensure_event_queue

router = APIRouter(prefix="/convert", tags=["convert"])


async def run_agent(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    queue = ensure_event_queue(job_id)

    def on_event(event: dict) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass
        if event.get("type") == "stage" and "progress" in event:
            update_job(
                job_id,
                stage=event.get("message", job.stage),
                progress=int(event.get("progress", job.progress)),
            )

    try:
        agent = ConverterAgent(create_llm_client(), on_event=on_event)
        result = await agent.run(
            Path(job.pdf_path),
            Path(job.template_path),
            job.id,
            job.client_id,
        )
        update_job(
            job_id,
            status="completed",
            stage="done",
            progress=100,
            output_path=result["output_path"],
            schema_map_path=result["schema_map_path"],
            mapping_plan_path=result["mapping_plan_path"],
            llm_cost_usd=result["cost_usd"],
            llm_tokens=result["tokens"],
        )
        queue.put_nowait({"type": "done", "message": "completed"})
    except Exception as e:
        update_job(job_id, status="failed", error=str(e), stage="failed")
        queue.put_nowait({"type": "error", "message": str(e)})


@router.post("/{job_id}")
async def start_convert(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == "processing":
        return {"status": "already_processing"}
    update_job(job_id, status="processing", stage="starting", progress=0)
    ensure_event_queue(job_id)
    asyncio.create_task(run_agent(job_id))
    return {"status": "started"}
