-- Phase 1 SQLite schema for Hybrid AI pipeline documents.
-- Apply with: python -m app.db_adapter migrate

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    pdf_path TEXT NOT NULL,
    template_path TEXT,
    resolved_scope TEXT,
    ir_json TEXT,
    filtered_ir_json TEXT,
    filtered_template_schema_json TEXT,
    dropped_element_count INTEGER,
    warnings_json TEXT,
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
