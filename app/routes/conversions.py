# app/routes/conversions.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models import Conversion, User, ConversionStatus
from app.auth import get_current_user
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class ConversionResponse(BaseModel):
    id: int
    filename: str
    date: datetime
    size: str
    status: str
    xml_content: Optional[str] = None
    
    class Config:
        from_attributes = True

@router.get("/", response_model=List[ConversionResponse])
async def get_conversions(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Conversion).filter(Conversion.user_id == current_user.id)
    
    if status:
        query = query.filter(Conversion.status == status)
    
    conversions = query.order_by(Conversion.created_at.desc()).offset(skip).limit(limit).all()
    
    return conversions

@router.get("/{conversion_id}", response_model=ConversionResponse)
async def get_conversion(
    conversion_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversion = db.query(Conversion).filter(
        Conversion.id == conversion_id,
        Conversion.user_id == current_user.id
    ).first()
    
    if not conversion:
        raise HTTPException(status_code=404, detail="Conversion not found")
    
    return conversion

@router.get("/stats")
async def get_conversion_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    total = db.query(Conversion).filter(Conversion.user_id == current_user.id).count()
    success = db.query(Conversion).filter(
        Conversion.user_id == current_user.id,
        Conversion.status == ConversionStatus.SUCCESS
    ).count()
    failed = db.query(Conversion).filter(
        Conversion.user_id == current_user.id,
        Conversion.status == ConversionStatus.FAILED
    ).count()
    processing = db.query(Conversion).filter(
        Conversion.user_id == current_user.id,
        Conversion.status == ConversionStatus.PROCESSING
    ).count()
    
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "processing": processing
    }