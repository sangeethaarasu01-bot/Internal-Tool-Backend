# app/routes/upload.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
import os
import shutil
from datetime import datetime
import aiofiles

from app.database import get_db
from app.models import User, Conversion, ConversionStatus
from app.auth import get_current_user
from app.services.pdf_processor import process_pdf

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 10485760))  # 10MB

@router.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    # Validate file size
    file_size = 0
    content = await file.read()
    file_size = len(content)
    await file.seek(0)  # Reset file pointer
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File size exceeds {MAX_FILE_SIZE/1024/1024}MB limit")
    
    # Create unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"{timestamp}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    # Save file
    async with aiofiles.open(file_path, 'wb') as out_file:
        content = await file.read()
        await out_file.write(content)
    
    # Create conversion record
    conversion = Conversion(
        user_id=current_user.id,
        filename=safe_filename,
        original_filename=file.filename,
        file_size=round(file_size / (1024 * 1024), 2),  # Convert to MB
        status=ConversionStatus.PENDING
    )
    db.add(conversion)
    db.commit()
    db.refresh(conversion)
    
    # Process in background
    background_tasks.add_task(process_pdf, conversion.id, file_path, db)
    
    return {
        "message": "File uploaded successfully",
        "conversion_id": conversion.id,
        "filename": file.filename,
        "status": "pending"
    }

@router.delete("/{conversion_id}")
async def delete_conversion(
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
    
    # Delete file
    file_path = os.path.join(UPLOAD_DIR, conversion.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    db.delete(conversion)
    db.commit()
    
    return {"message": "Conversion deleted successfully"}