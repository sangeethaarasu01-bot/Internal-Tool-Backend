# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

from app.database import engine, Base
from app.routes import auth, conversions, upload

load_dotenv()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="IEEE XML Converter API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create upload directory
os.makedirs(os.getenv("UPLOAD_DIR", "./uploads"), exist_ok=True)

# Include routes
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
app.include_router(conversions.router, prefix="/api/conversions", tags=["Conversions"])

@app.get("/")
async def root():
    return {"message": "IEEE XML Converter API is running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}