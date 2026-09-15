from __future__ import annotations

from app.main import app


def test_existing_conversion_routes_still_registered() -> None:
    paths = app.openapi()["paths"]
    assert any(path.startswith("/api/conversions") for path in paths)
    assert "/api/extractions" in paths or any(
        path.startswith("/api/extractions") for path in paths
    )
    assert any(path.endswith("/text") and "extractions" in path for path in paths)
    assert "/api/extractions/{extraction_id}/scope" in paths
    assert "/api/extractions/{extraction_id}/template" in paths
    assert "/api/extractions/{extraction_id}/semantic-map" in paths
