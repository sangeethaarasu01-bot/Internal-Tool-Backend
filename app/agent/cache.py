"""Persistent schema map cache keyed by template hash."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings
from app.models.schema_map import SchemaMap


class SchemaCache:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or settings.schemas_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, template_hash: str) -> Path:
        return self.base_dir / f"{template_hash}.json"

    def get(self, template_hash: str) -> SchemaMap | None:
        path = self._path(template_hash)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        analyzed = datetime.fromisoformat(data.get("analyzed_at", datetime.utcnow().isoformat()))
        if datetime.utcnow() - analyzed > timedelta(days=settings.SCHEMA_CACHE_TTL_DAYS):
            return None
        return SchemaMap(**data)

    def set(self, template_hash: str, schema_map: SchemaMap) -> None:
        path = self._path(template_hash)
        path.write_text(schema_map.model_dump_json(indent=2), encoding="utf-8")

    def invalidate(self, template_hash: str) -> None:
        path = self._path(template_hash)
        if path.exists():
            path.unlink()
