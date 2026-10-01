"""File upload endpoint."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.db import Client, Job, get_session
from app.utils.logger import logger

router = APIRouter(prefix="/upload", tags=["upload"])


async def _save_upload_to_disk(upload: UploadFile, dest: Path) -> int:
    """Write multipart upload without blocking the event loop (large PDFs)."""

    def _write() -> int:
        nbytes = 0
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
            nbytes = dest.stat().st_size
        return nbytes

    return await asyncio.to_thread(_write)


@router.post("")
async def upload_files(
    pdf: UploadFile = File(...),
    template: UploadFile | None = File(None),
    client_id: str | None = Form(None),
) -> dict:
    t0 = time.perf_counter()
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "pdf must be a .pdf file")

    job_id = str(uuid4())
    job_dir = settings.uploads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "paper.pdf"
    pdf_bytes = await _save_upload_to_disk(pdf, pdf_path)
    logger.info("Upload job {}: saved PDF {} ({} bytes)", job_id, pdf.filename, pdf_bytes)

    template_path: Path
    template_filename: str | None = None

    if client_id:
        with get_session() as session:
            client = session.get(Client, client_id)
            if not client:
                raise HTTPException(404, "Client not found")
            template_path = Path(client.template_path)
            template_filename = Path(client.template_path).name
    else:
        if not template or not template.filename:
            raise HTTPException(400, "template required when client_id not set")
        if not template.filename.lower().endswith(".xml"):
            raise HTTPException(400, "template must be .xml")
        template_path = job_dir / "template.xml"
        await _save_upload_to_disk(template, template_path)
        template_filename = template.filename

    job = Job(
        id=job_id,
        client_id=client_id,
        status="uploaded",
        stage="uploaded",
        progress=0,
        pdf_filename=pdf.filename,
        template_filename=template_filename,
        pdf_path=str(pdf_path),
        template_path=str(template_path),
    )
    with get_session() as session:
        session.add(job)
        session.commit()

    logger.info(
        "Upload job {} ready in {:.2f}s",
        job_id,
        time.perf_counter() - t0,
    )
    return {
        "job_id": job_id,
        "pdf_filename": pdf.filename,
        "template_filename": template_filename,
        "client_id": client_id,
    }
