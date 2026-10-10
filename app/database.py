from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import certifi
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env", override=False)
if os.getenv("USE_LOCAL_MONGO", "").strip().lower() in {"1", "true", "yes"}:
    load_dotenv(_root / ".env.local", override=True)

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


def mongo_user_error(exc: Exception | None = None) -> str:
    """Human-readable message for any PyMongo failure (connection or write)."""
    if exc is None:
        return mongo_connect_error()
    name = type(exc).__name__
    detail = (str(exc) or "").strip()
    lower = detail.lower()

    if name in {"ServerSelectionTimeoutError", "NetworkTimeout", "ConnectionFailure", "ConfigurationError"}:
        return mongo_connect_error(exc)

    if name == "OperationFailure" or "operationfailure" in lower:
        if "larger than" in lower or "16777216" in detail or "too large" in lower:
            return (
                "MongoDB could not save this extraction update: the document would exceed "
                "Atlas's 16MB per-document limit (often after uploading a large book template "
                "on top of a large PDF extraction). "
                f"Server detail: {detail[:480]}"
            )
        if "auth" in lower or "authentication" in lower or "bad auth" in lower:
            return (
                "MongoDB authentication failed. Verify MONGODB_URI user, password, and database name. "
                f"Detail: {detail[:400]}"
            )
        return (
            "MongoDB rejected the database operation (OperationFailure). "
            "This is not always caused by Network Access / IP allowlisting — "
            "check the server detail below and Atlas cluster status (not paused). "
            f"Detail: {detail[:500]}"
        )

    if name == "DocumentTooLarge":
        return (
            "MongoDB document too large to store. "
            f"Detail: {detail[:400]}"
        )

    return mongo_connect_error(exc)


def mongo_connect_error(exc: Exception | None = None) -> str:
    kind = f" ({type(exc).__name__})" if exc else ""
    detail = str(exc) if exc else ""
    if uses_local_mongo():
        return (
            "MongoDB URI is pointing at localhost:27017. "
            "Start a local MongoDB service, or set MONGODB_URI in .env to your "
            "Atlas mongodb+srv:// connection string."
        )
    if "SSL" in detail or "TLS" in detail:
        return (
            f"Could not connect to MongoDB Atlas{kind}. "
            "SSL handshake failed — your current IP is usually not on the Atlas "
            "allowlist. In MongoDB Atlas: Network Access → Add IP Address → "
            "add your IP (or 0.0.0.0/0 for dev), wait 1-2 minutes, restart. "
            "Also use Python 3.12 (not 3.13/3.14) for local dev."
        )
    return (
        f"Could not connect to MongoDB Atlas{kind}. "
        "In Atlas Network Access add 0.0.0.0/0 (Allow access from anywhere), "
        "wait 1-2 minutes, then retry."
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


def extractions_col() -> Collection:
    return get_db()["extractions"]


def book_documents_col() -> Collection:
    """Per-chapter DocBook fragments keyed by extraction_id + document_id."""
    return get_db()["book_documents"]


def ensure_indexes() -> None:
    conversions_col().create_index([("created_at", DESCENDING)])
    conversions_col().create_index([("status", ASCENDING)])
    conversions_col().create_index([("original_filename", ASCENDING)])
    extractions_col().create_index([("created_at", DESCENDING)])
    extractions_col().create_index([("status", ASCENDING)])
    extractions_col().create_index([("filename", ASCENDING)])
    extractions_col().create_index([("original_filename", ASCENDING)])
    book_documents_col().create_index([("extraction_id", ASCENDING)])
    book_documents_col().create_index(
        [("extraction_id", ASCENDING), ("document_id", ASCENDING)],
        unique=True,
    )
    get_db()["llm_calls"].create_index([("document_id", ASCENDING)])
    get_db()["llm_calls"].create_index([("timestamp", DESCENDING)])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
