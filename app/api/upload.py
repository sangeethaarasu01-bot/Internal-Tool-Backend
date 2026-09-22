"""File upload endpoint."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.db import Client, Job, get_session

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("")
async def upload_files(
    pdf: UploadFile = File(...),
    template: UploadFile | None = File(None),
    client_id: str | None = Form(None),
) -> dict:
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "pdf must be a .pdf file")

    job_id = str(uuid4())
    job_dir = settings.uploads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "paper.pdf"
    with pdf_path.open("wb") as f:
        shutil.copyfileobj(pdf.file, f)

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
        with template_path.open("wb") as f:
            shutil.copyfileobj(template.file, f)
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

    return {
        "job_id": job_id,
        "pdf_filename": pdf.filename,
        "template_filename": template_filename,
        "client_id": client_id,
    }
