"""API response models for jobs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class JobRead(BaseModel):
    id: str
    client_id: str | None
    status: Literal["uploaded", "processing", "completed", "failed", "deleted"]
    stage: str
    progress: int
    pdf_filename: str
    template_filename: str | None
    pdf_path: str
    template_path: str
    output_path: str | None
    schema_map_path: str | None
    mapping_plan_path: str | None
    error: str | None
    llm_cost_usd: float
    llm_tokens: int
    created_at: datetime
    updated_at: datetime


class JobEventRead(BaseModel):
    id: int
    job_id: str
    event_type: str
    data: str
    created_at: datetime
