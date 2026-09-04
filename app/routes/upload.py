"""File selection is frontend-only. MongoDB records are created by POST /api/conversions."""

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException

from app.database import conversions_col
import os

router = APIRouter()


@router.delete("/{conversion_id}")
async def delete_conversion(conversion_id: str):
    try:
        oid = ObjectId(conversion_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid conversion id")

    conversion = conversions_col().find_one({"_id": oid})
    if not conversion:
        raise HTTPException(status_code=404, detail="Conversion not found")

    file_path = conversion.get("file_path")
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    conversions_col().delete_one({"_id": oid})
    return {"message": "Conversion deleted successfully"}
