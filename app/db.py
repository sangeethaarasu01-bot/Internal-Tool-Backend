"""SQLModel database setup and ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import settings

engine = create_engine(settings.DB_URL, connect_args={"check_same_thread": False})


class Job(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    client_id: Optional[str] = Field(default=None, foreign_key="client.id")
    status: str = Field(default="uploaded")
    stage: str = Field(default="uploaded")
    progress: int = Field(default=0)
    pdf_filename: str
    template_filename: Optional[str] = None
    pdf_path: str
    template_path: str
    output_path: Optional[str] = None
    schema_map_path: Optional[str] = None
    mapping_plan_path: Optional[str] = None
    error: Optional[str] = None
    llm_cost_usd: float = 0.0
    llm_tokens: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Client(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    slug: str = Field(unique=True, index=True)
    template_path: str
    schema_map_path: Optional[str] = None
    template_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    event_type: str
    data: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)


def get_job(job_id: str) -> Job | None:
    with get_session() as session:
        return session.get(Job, job_id)


def update_job(job_id: str, **kwargs) -> Job | None:
    with get_session() as session:
        job = session.get(Job, job_id)
        if not job:
            return None
        for k, v in kwargs.items():
            setattr(job, k, v)
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def list_jobs(include_deleted: bool = False) -> list[Job]:
    with get_session() as session:
        stmt = select(Job)
        jobs = list(session.exec(stmt).all())
        if not include_deleted:
            jobs = [j for j in jobs if j.status != "deleted"]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)
