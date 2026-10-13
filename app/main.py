"""FastAPI application entrypoint."""

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import clients, convert, jobs, refine, schema, stream, upload
from app.routes import extractions
from app.config import settings
from app.database import ensure_indexes
from app.db import create_db_and_tables
from app.events import EVENTS, EVENT_TIMESTAMPS
from app.services.data_retention import run_retention_if_enabled
from app.utils.logger import logger


async def _cleanup_old_events() -> None:
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for jid, ts in list(EVENT_TIMESTAMPS.items()):
            if now - ts > 3600:
                EVENTS.pop(jid, None)
                EVENT_TIMESTAMPS.pop(jid, None)


async def _periodic_data_retention() -> None:
    interval_sec = max(3600, settings.DATA_RETENTION_INTERVAL_HOURS * 3600)
    while True:
        await asyncio.sleep(interval_sec)
        try:
            run_retention_if_enabled()
        except Exception:
            logger.exception("Scheduled data retention purge failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    settings.ensure_data_dirs()
    try:
        ensure_indexes()
    except Exception:
        logger.warning("MongoDB index setup skipped or failed", exc_info=True)
    try:
        run_retention_if_enabled()
    except Exception:
        logger.exception("Startup data retention purge failed")
    logger.info("IEEE XML Converter API started")
    task = asyncio.create_task(_cleanup_old_events())
    retention_task = asyncio.create_task(_periodic_data_retention())
    yield
    retention_task.cancel()
    task.cancel()


app = FastAPI(title="IEEE XML Converter API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(convert.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(refine.router, prefix="/api")
app.include_router(clients.router, prefix="/api")
app.include_router(schema.router, prefix="/api")
app.include_router(extractions.router, prefix="/api/extractions", tags=["extractions"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}
