from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ConversionOut(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_size: float
    page_count: Optional[int] = None
    status: str
    xml_content: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class ConversionListItem(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_size: float
    page_count: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


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
