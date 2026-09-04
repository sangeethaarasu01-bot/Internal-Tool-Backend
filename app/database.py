from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import certifi
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

MONGODB_URI = (
    (os.getenv("MONGODB_URI") or "mongodb://localhost:27017")
    .strip()
    .strip('"')
    .strip("'")
)
MONGODB_DB = (os.getenv("MONGODB_DB") or "ieee_converter").strip()

_client: MongoClient | None = None


def uses_local_mongo() -> bool:
    return "localhost" in MONGODB_URI or "127.0.0.1" in MONGODB_URI


def mongo_connect_error(exc: Exception | None = None) -> str:
    kind = f" ({type(exc).__name__})" if exc else ""
    if uses_local_mongo():
        return (
            "MongoDB URI is pointing at localhost:27017. "
            "On Render, add Environment variable MONGODB_URI with your Atlas "
            "mongodb+srv:// connection string, then redeploy."
        )
    return (
        f"Could not connect to MongoDB Atlas{kind}. "
        "In Atlas Network Access add 0.0.0.0/0 (Allow access from anywhere), "
        "wait 1-2 minutes, then retry. Local IP-only allowlists block Render."
    )


def get_client() -> MongoClient:
    global _client
    if _client is None:
        options: dict = {
            "serverSelectionTimeoutMS": 30000,
            "connectTimeoutMS": 20000,
            "retryWrites": True,
        }
        if "mongodb.net" in MONGODB_URI or MONGODB_URI.startswith("mongodb+srv://"):
            options["tlsCAFile"] = certifi.where()
            # Render/some hosts block OCSP; Atlas TLS handshake then fails.
            options["tlsDisableOCSPEndpointCheck"] = True
        _client = MongoClient(MONGODB_URI, **options)
    return _client


def get_db() -> Database:
    return get_client()[MONGODB_DB]


def conversions_col() -> Collection:
    return get_db()["conversions"]


def ensure_indexes() -> None:
    conversions_col().create_index([("created_at", DESCENDING)])
    conversions_col().create_index([("status", ASCENDING)])
    conversions_col().create_index([("original_filename", ASCENDING)])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
