import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import MONGODB_DB, ensure_indexes, uses_local_mongo
from app.routes import conversions, upload

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="IEEE XML Converter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "https://internal-tool-sepia.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(os.getenv("UPLOAD_DIR", "./uploads"), exist_ok=True)


@app.on_event("startup")
def startup() -> None:
    try:
        ensure_indexes()
        logging.info("MongoDB connected: %s", MONGODB_DB)
    except Exception:
        if uses_local_mongo():
            logging.error(
                "MongoDB URI is localhost. Set MONGODB_URI on Render to your Atlas mongodb+srv:// string."
            )
        else:
            logging.error(
                "Atlas URI is set but connection failed. Allow 0.0.0.0/0 in Atlas Network Access "
                "and set PYTHON_VERSION=3.12.8 on Render."
            )
        logging.exception("MongoDB connection failed on startup")

app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
app.include_router(conversions.router, prefix="/api/conversions", tags=["Conversions"])


@app.get("/")
async def root():
    return {"message": "IEEE XML Converter API is running", "db": "ieee_converter"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
