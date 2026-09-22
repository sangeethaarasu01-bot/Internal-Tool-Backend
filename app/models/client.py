"""Client API models."""

from datetime import datetime

from pydantic import BaseModel


class ClientCreate(BaseModel):
    name: str
    slug: str


class ClientRead(BaseModel):
    id: str
    name: str
    slug: str
    template_path: str
    schema_map_path: str | None
    template_hash: str
    created_at: datetime
    updated_at: datetime
