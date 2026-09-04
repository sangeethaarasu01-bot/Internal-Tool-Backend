import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import ensure_indexes
from app.routes import conversions, upload

load_dotenv()
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
        logging.info("MongoDB connected: ieee_converter")
    except Exception:
        logging.exception("MongoDB connection failed on startup")

app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
app.include_router(conversions.router, prefix="/api/conversions", tags=["Conversions"])


@app.get("/")
async def root():
    return {"message": "IEEE XML Converter API is running", "db": "ieee_converter"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
