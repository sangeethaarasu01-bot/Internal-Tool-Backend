"""Quick MongoDB connectivity check. Run: python scripts/test_mongo.py"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dotenv import load_dotenv
from pathlib import Path

_root = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_root))
load_dotenv(_root / ".env", override=False)
if os.getenv("USE_LOCAL_MONGO", "").strip().lower() in {"1", "true", "yes"}:
    load_dotenv(_root / ".env.local", override=True)

from app.database import MONGODB_DB, MONGODB_URI, ensure_indexes, get_client, uses_local_mongo


def public_ip() -> str:
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5) as r:
            return json.load(r)["ip"]
    except Exception:
        return "unknown"


def main() -> None:
    print(f"Public IP (add this in Atlas Network Access): {public_ip()}")
    print(f"MongoDB URI target: {'localhost' if uses_local_mongo() else 'Atlas'}")
    print(f"Database: {MONGODB_DB}")
    try:
        ensure_indexes()
        get_client().admin.command("ping")
        print("OK: connected and indexes ready")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        if not uses_local_mongo() and "SSL" in str(exc):
            print(
                "Fix: Atlas → Network Access → Add IP Address → "
                f"{public_ip()} or 0.0.0.0/0, wait 2 min, retry."
            )
        if uses_local_mongo():
            print("Fix: start local MongoDB (service MongoDB or mongod).")


if __name__ == "__main__":
    main()
