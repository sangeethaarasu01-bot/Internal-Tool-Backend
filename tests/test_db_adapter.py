"""Tests for SQLite db_adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import db_adapter


@pytest.fixture()
def sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))
    db_adapter.migrate()
    return db_file


def test_migrate_creates_documents_table(sqlite_db: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(sqlite_db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "documents" in tables
    assert "schema_migrations" in tables


def test_create_and_get_document(sqlite_db: Path) -> None:
    record = db_adapter.create_document("/tmp/paper.pdf", template_path="/tmp/template.xml")
    loaded = db_adapter.get_document(record.document_id)
    assert loaded.pdf_path == "/tmp/paper.pdf"
    assert loaded.template_path == "/tmp/template.xml"
    assert loaded.status == "uploaded"


def test_save_scope_result(sqlite_db: Path) -> None:
    record = db_adapter.create_document("/tmp/paper.pdf")
    scope_result = {
        "resolved_scope": "front",
        "filtered_ir": {"front": {"title": None}, "body": {"sections": []}, "back": {}},
        "filtered_template_schema": {"required_paths": []},
        "dropped_element_count": 3,
        "warnings": ["example warning"],
    }
    updated = db_adapter.save_scope_result(record.document_id, scope_result)
    assert updated.resolved_scope == "front"
    assert updated.dropped_element_count == 3
    assert updated.status == "scoped"
    assert updated.warnings == ["example warning"]
    assert updated.filtered_ir_json is not None
