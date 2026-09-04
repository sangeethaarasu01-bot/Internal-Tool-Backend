from __future__ import annotations

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "ieee_converter")

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
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
