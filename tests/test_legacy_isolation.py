"""Verify legacy pipeline is isolated from live routes."""

from __future__ import annotations

import inspect

from app.routes import conversions
from app.services.conversion_stub import reject_legacy_conversion


def test_conversions_route_does_not_import_legacy_pipeline() -> None:
    source = inspect.getsource(conversions)
    assert "app.legacy" not in source
    assert "pdf_processor" not in source
    assert "ieee_jats" not in source
    assert "reject_legacy_conversion" in source


def test_legacy_modules_remain_importable() -> None:
    from app.legacy.ieee_jats import generate_ieee_jats
    from app.legacy.pdf_extractor import extract_paper

    assert callable(generate_ieee_jats)
    assert callable(extract_paper)
    assert callable(reject_legacy_conversion)
