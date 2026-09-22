"""FastAPI application entrypoint."""

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import clients, convert, jobs, refine, schema, stream, upload
from app.config import settings
from app.db import create_db_and_tables
from app.events import EVENTS, EVENT_TIMESTAMPS
from app.utils.logger import logger


async def _cleanup_old_events() -> None:
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for jid, ts in list(EVENT_TIMESTAMPS.items()):
            if now - ts > 3600:
                EVENTS.pop(jid, None)
                EVENT_TIMESTAMPS.pop(jid, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    settings.ensure_data_dirs()
    logger.info("IEEE XML Converter API started")
    task = asyncio.create_task(_cleanup_old_events())
    yield
    task.cancel()


app = FastAPI(title="IEEE XML Converter API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(convert.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(refine.router, prefix="/api")
app.include_router(clients.router, prefix="/api")
app.include_router(schema.router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}
