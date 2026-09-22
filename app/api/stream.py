"""SSE stream for job events."""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.db import get_job, update_job
from app.events import ensure_event_queue

router = APIRouter(prefix="/stream", tags=["stream"])


@router.get("/{job_id}")
async def stream_job(job_id: str) -> EventSourceResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    queue = ensure_event_queue(job_id)

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": json.dumps({"type": "ping"})}
                continue
            etype = event.get("type", "log")
            if etype == "stage":
                update_job(
                    job_id,
                    stage=str(event.get("message", "")),
                    progress=int(event.get("progress", 0)),
                )
            yield {"event": etype, "data": json.dumps(event)}
            if etype in ("done", "error"):
                break

    return EventSourceResponse(event_generator())
