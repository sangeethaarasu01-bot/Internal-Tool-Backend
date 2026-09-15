"""SQLite persistence adapter for Phase 2 API endpoints (/upload, /scope, /generate).

MongoDB remains in use for existing conversion/extraction routes.  This adapter
is the dev-store for the new Hybrid AI document lifecycle.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _ROOT / "data" / "ieee_converter.db"
_MIGRATIONS_DIR = _ROOT / "migrations"
_SCHEMA_VERSION = 1


@dataclass
class DocumentRecord:
    document_id: str
    pdf_path: str
    template_path: str | None
    resolved_scope: str | None
    ir_json: dict[str, Any] | None
    filtered_ir_json: dict[str, Any] | None
    filtered_template_schema_json: dict[str, Any] | None
    dropped_element_count: int | None
    warnings: list[str]
    status: str
    created_at: str
    updated_at: str


def db_path() -> Path:
    configured = os.getenv("SQLITE_DB_PATH", "").strip()
    return Path(configured) if configured else _DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate() -> None:
    """Apply pending SQL migrations."""
    with connect() as conn:
        current = _current_schema_version(conn)
        if current >= _SCHEMA_VERSION:
            return
        sql = (_MIGRATIONS_DIR / "001_initial_schema.sql").read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (_SCHEMA_VERSION, _utcnow_iso()),
        )
        conn.commit()


def _current_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0] or 0)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_document(pdf_path: str, template_path: str | None = None) -> DocumentRecord:
    """Insert a new uploaded document row."""
    migrate()
    document_id = str(uuid.uuid4())
    now = _utcnow_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                document_id, pdf_path, template_path, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'uploaded', ?, ?)
            """,
            (document_id, pdf_path, template_path, now, now),
        )
        conn.commit()
    return get_document(document_id)


def update_document(document_id: str, **fields: Any) -> DocumentRecord:
    """Update whitelisted document fields."""
    migrate()
    allowed = {
        "template_path",
        "resolved_scope",
        "ir_json",
        "filtered_ir_json",
        "filtered_template_schema_json",
        "dropped_element_count",
        "warnings_json",
        "status",
    }
    json_fields = {
        "ir_json",
        "filtered_ir_json",
        "filtered_template_schema_json",
        "warnings_json",
    }
    updates: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Unsupported field: {key}")
        if key in json_fields and isinstance(value, (dict, list)):
            updates[key] = json.dumps(value, ensure_ascii=False)
        else:
            updates[key] = value

    if not updates:
        return get_document(document_id)

    updates["updated_at"] = _utcnow_iso()
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [document_id]

    with connect() as conn:
        conn.execute(f"UPDATE documents SET {columns} WHERE document_id = ?", values)
        conn.commit()
    return get_document(document_id)


def save_scope_result(document_id: str, scope_result: dict[str, Any]) -> DocumentRecord:
    """Persist output from scope_resolver.resolve_scope()."""
    return update_document(
        document_id,
        resolved_scope=scope_result.get("resolved_scope"),
        filtered_ir_json=scope_result.get("filtered_ir"),
        filtered_template_schema_json=scope_result.get("filtered_template_schema"),
        dropped_element_count=scope_result.get("dropped_element_count"),
        warnings_json=scope_result.get("warnings", []),
        status="scoped",
    )


def get_document(document_id: str) -> DocumentRecord:
    migrate()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"Document not found: {document_id}")
    return _row_to_record(row)


def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
    return DocumentRecord(
        document_id=row["document_id"],
        pdf_path=row["pdf_path"],
        template_path=row["template_path"],
        resolved_scope=row["resolved_scope"],
        ir_json=_load_json(row["ir_json"]),
        filtered_ir_json=_load_json(row["filtered_ir_json"]),
        filtered_template_schema_json=_load_json(row["filtered_template_schema_json"]),
        dropped_element_count=row["dropped_element_count"],
        warnings=_load_json(row["warnings_json"]) or [],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _load_json(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


if __name__ == "__main__":
    migrate()
    print(f"Applied schema version {_SCHEMA_VERSION} to {db_path()}")
