"""Client CRUD and schema reanalysis."""

import json
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agent.schema_analyzer import SchemaAnalyzer
from app.config import settings
from sqlmodel import select

from app.db import Client, get_session
from app.llm.client import create_llm_client
from app.utils.hashing import sha256_file

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("")
async def create_client(
    name: str = Form(...),
    slug: str = Form(...),
    template: UploadFile = File(...),
) -> dict:
    if not template.filename or not template.filename.lower().endswith(".xml"):
        raise HTTPException(400, "template must be .xml")
    client_id = str(uuid4())
    client_dir = settings.uploads_dir / "clients" / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    template_path = client_dir / "template.xml"
    with template_path.open("wb") as f:
        shutil.copyfileobj(template.file, f)
    th = sha256_file(template_path)
    client = Client(
        id=client_id,
        name=name,
        slug=slug,
        template_path=str(template_path),
        template_hash=th,
    )
    with get_session() as session:
        existing = session.exec(select(Client).where(Client.slug == slug)).first()
        if existing:
            raise HTTPException(400, "slug already exists")
        session.add(client)
        session.commit()
        session.refresh(client)
    return client.model_dump()


@router.get("")
def list_clients() -> list[dict]:
    with get_session() as session:
        clients = list(session.exec(select(Client)).all())
    return [c.model_dump() for c in clients]


@router.get("/{client_id}")
def get_client(client_id: str) -> dict:
    with get_session() as session:
        client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return client.model_dump()


@router.delete("/{client_id}")
def delete_client(client_id: str) -> dict:
    with get_session() as session:
        client = session.get(Client, client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        session.delete(client)
        session.commit()
    return {"deleted": True}


@router.post("/{client_id}/reanalyze")
async def reanalyze_client(client_id: str) -> dict:
    with get_session() as session:
        client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    analyzer = SchemaAnalyzer(create_llm_client())
    schema = await analyzer.analyze(Path(client.template_path))
    schema_path = settings.schemas_dir / f"client_{client_id}.json"
    schema_path.write_text(schema.model_dump_json(indent=2), encoding="utf-8")
    with get_session() as session:
        c = session.get(Client, client_id)
        if c:
            c.schema_map_path = str(schema_path)
            session.add(c)
            session.commit()
    return {"schema_map_path": str(schema_path), "elements": len(schema.elements)}
