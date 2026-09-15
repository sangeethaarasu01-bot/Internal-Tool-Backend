from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ConversionOut(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_size: float
    page_count: int | None = None
    status: str
    xml_content: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    class Config:
        populate_by_name = True


class ConversionListItem(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_size: float
    page_count: int | None = None
    status: str
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class UploadResponse(BaseModel):
    message: str
    conversion_id: str
    filename: str
    status: str


class StatsResponse(BaseModel):
    total: int
    success: int
    failed: int
    processing: int
    pending: int = 0
