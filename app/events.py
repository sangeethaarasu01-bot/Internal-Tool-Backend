"""In-memory SSE event queues per job."""

import asyncio
import time

EVENTS: dict[str, asyncio.Queue] = {}
EVENT_TIMESTAMPS: dict[str, float] = {}


def ensure_event_queue(job_id: str) -> asyncio.Queue:
    if job_id not in EVENTS:
        EVENTS[job_id] = asyncio.Queue(maxsize=500)
        EVENT_TIMESTAMPS[job_id] = time.time()
    return EVENTS[job_id]
