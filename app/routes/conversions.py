import os
from datetime import datetime
from typing import Optional

import aiofiles
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pymongo.errors import PyMongoError

from app.database import conversions_col, mongo_connect_error, utcnow
from app.services.pdf_processor import process_pdf

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 20 * 1024 * 1024))
DONE_STATUSES = ["completed", "success"]

router = APIRouter()


def _serialize(doc: dict, include_xml: bool = True) -> dict:
    return {
        "id": str(doc["_id"]),
        "filename": doc.get("original_filename") or doc.get("filename"),
        "original_filename": doc.get("original_filename"),
        "file_size": doc.get("file_size"),
        "page_count": doc.get("page_count"),
        "status": doc.get("status"),
        "xml_content": doc.get("xml_content") if include_xml else None,
        "error_message": doc.get("error_message"),
        "title": doc.get("title"),
        "doi": doc.get("doi"),
        "created_at": doc.get("created_at"),
        "completed_at": doc.get("completed_at"),
    }


def _oid(conversion_id: str) -> ObjectId:
    try:
        return ObjectId(conversion_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid conversion id")


@router.post("")
@router.post("/")
async def start_conversion(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Create one conversions document and start PDF → IEEE XML. Called only by Convert."""
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content = await file.read()
    file_size = len(content)
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds {MAX_FILE_SIZE / 1024 / 1024:.0f}MB limit",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{os.path.basename(filename)}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)

    async with aiofiles.open(file_path, "wb") as out_file:
        await out_file.write(content)

    doc = {
        "filename": safe_name,
        "original_filename": filename,
        "file_path": file_path,
        "file_size": round(file_size / (1024 * 1024), 2),
        "status": "processing",
        "xml_content": None,
        "error_message": None,
        "page_count": None,
        "title": None,
        "doi": None,
        "created_at": utcnow(),
        "completed_at": None,
    }
    try:
        result = conversions_col().insert_one(doc)
    except PyMongoError as exc:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))
    conversion_id = str(result.inserted_id)

    background_tasks.add_task(process_pdf, conversion_id, file_path)

    return {
        "message": "Conversion started",
        "conversion_id": conversion_id,
        "filename": filename,
        "status": "processing",
    }


@router.get("/stats")
async def get_conversion_stats():
    col = conversions_col()
    return {
        "total": col.count_documents({}),
        "success": col.count_documents({"status": {"$in": DONE_STATUSES}}),
        "failed": col.count_documents({"status": "failed"}),
        "processing": col.count_documents({"status": {"$in": ["processing", "pending"]}}),
        "pending": col.count_documents({"status": "pending"}),
    }


@router.get("")
@router.get("/")
async def get_conversions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
):
    query = {}
    if status and status != "all":
        if status == "processing":
            query["status"] = {"$in": ["processing", "pending"]}
        elif status in DONE_STATUSES:
            query["status"] = {"$in": DONE_STATUSES}
        else:
            query["status"] = status

    try:
        cursor = (
            conversions_col()
            .find(query, {"xml_content": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        return [_serialize(doc, include_xml=False) for doc in cursor]
    except PyMongoError as exc:
        raise HTTPException(status_code=503, detail=mongo_connect_error(exc))


@router.get("/{conversion_id}")
async def get_conversion(conversion_id: str):
    doc = conversions_col().find_one({"_id": _oid(conversion_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Conversion not found")
    return _serialize(doc, include_xml=True)


@router.get("/{conversion_id}/download")
async def download_xml(conversion_id: str):
    doc = conversions_col().find_one({"_id": _oid(conversion_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Conversion not found")
    if doc.get("status") not in DONE_STATUSES or not doc.get("xml_content"):
        raise HTTPException(status_code=400, detail="XML is not ready")

    name = (doc.get("original_filename") or "article.pdf").rsplit(".", 1)[0] + ".xml"
    return Response(
        content=doc["xml_content"],
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/{conversion_id}/retry")
async def retry_conversion(conversion_id: str, background_tasks: BackgroundTasks):
    doc = conversions_col().find_one({"_id": _oid(conversion_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Conversion not found")
    file_path = doc.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="Original PDF is no longer available")

    conversions_col().update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "status": "processing",
                "error_message": None,
                "completed_at": None,
            }
        },
    )
    background_tasks.add_task(process_pdf, conversion_id, file_path)
    return {"message": "Retry started", "conversion_id": conversion_id, "status": "processing"}
