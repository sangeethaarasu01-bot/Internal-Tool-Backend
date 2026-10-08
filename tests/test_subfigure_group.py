from __future__ import annotations

from app.pipeline.phase1.figure_detection import FigureRegionCandidate
from app.pipeline.phase1.subfigure_group import resolve_subfigure_group


def test_resolve_subfigure_group_merges_nearby_panels() -> None:
    regions = [
        FigureRegionCandidate(bbox=[70.0, 120.0, 200.0, 220.0], source="raster_image", area=10_000),
        FigureRegionCandidate(bbox=[210.0, 120.0, 340.0, 220.0], source="raster_image", area=10_000),
        FigureRegionCandidate(bbox=[70.0, 230.0, 340.0, 330.0], source="raster_image", area=10_000),
    ]
    composite, subfigures = resolve_subfigure_group(
        "Fig. 1. Example (a) left (b) middle (c) bottom.",
        regions[0].bbox,
        regions,
        caption_bbox=[60.0, 340.0, 350.0, 360.0],
    )
    assert composite[1] <= 120.0
    assert composite[3] >= 330.0
    assert len(subfigures) >= 2
