"""Merge overlapping table candidates (detection + post-validation)."""



from __future__ import annotations



from typing import Callable, TypeVar



from app.pipeline.table_extraction.geometry import iou, overlap_ratio_of_smaller

from app.pipeline.table_extraction.postprocess import sanitize_rows

from app.pipeline.table_extraction.quality import score_candidate

from app.pipeline.table_extraction.types import PageIngest, ProcessedTable, RawDetectedTable



T = TypeVar("T")



MERGE_IOU_THRESHOLD = 0.30

MERGE_OVERLAP_SMALLER_THRESHOLD = 0.50





def _cell_fill(rows: list[list[str]]) -> float:

    rows = sanitize_rows(rows)

    if not rows:

        return 0.0

    nrows = len(rows)

    ncols = max(len(r) for r in rows)

    total = nrows * ncols

    nonempty = sum(1 for row in rows for cell in row if (cell or "").strip())

    return nonempty / total if total else 0.0





def _structure_rank_raw(

    cand: RawDetectedTable,

    page: PageIngest,

    caption_nearby: bool,

) -> float:

    rows = sanitize_rows(cand.rows)

    nrows = len(rows)

    ncols = max(len(r) for r in rows) if rows else 0

    fill = _cell_fill(rows)

    score = 0.0

    if nrows >= 2 and ncols >= 2:

        score += 10.0

    if fill >= 0.40:

        score += 6.0

    if caption_nearby:

        score += 8.0

    quality, _, _ = score_candidate(

        rows,

        cand.bbox,

        page,

        caption_nearby=caption_nearby,

        figure_regions=page.figure_regions,

    )

    score += quality * 12.0

    return score





def _structure_rank_processed(tbl: ProcessedTable) -> float:

    rows = sanitize_rows(([tbl.headers] + tbl.rows) if tbl.headers else tbl.rows)

    nrows = len(rows)

    ncols = max(len(r) for r in rows) if rows else 0

    fill = _cell_fill(rows)

    score = 0.0

    if nrows >= 2 and ncols >= 2:

        score += 10.0

    if fill >= 0.40:

        score += 6.0

    if tbl.caption_detected:

        score += 8.0

    score += tbl.confidence * 10.0

    return score





def _same_caption(a_caption: str | None, b_caption: str | None) -> bool:

    if not a_caption or not b_caption:

        return False

    return a_caption.strip().splitlines()[0].casefold() == b_caption.strip().splitlines()[0].casefold()





def _should_merge_bboxes(a: list[float], b: list[float]) -> bool:

    if iou(a, b) > MERGE_IOU_THRESHOLD:

        return True

    if overlap_ratio_of_smaller(a, b) > MERGE_OVERLAP_SMALLER_THRESHOLD:

        return True

    return False





def merge_raw_candidates(

    candidates: list[RawDetectedTable],

    page: PageIngest,

    caption_nearby_fn: Callable[[list[float]], bool],

    caption_for_bbox_fn: Callable[[list[float]], str | None] | None = None,

) -> list[RawDetectedTable]:

    if len(candidates) <= 1:

        return list(candidates)



    ranked: list[tuple[float, RawDetectedTable, bool, str | None]] = []

    for cand in candidates:

        near = caption_nearby_fn(cand.bbox)

        cap = caption_for_bbox_fn(cand.bbox) if caption_for_bbox_fn else None

        ranked.append((_structure_rank_raw(cand, page, near), cand, near, cap))

    ranked.sort(key=lambda t: t[0], reverse=True)



    kept: list[tuple[float, RawDetectedTable, bool, str | None]] = []

    for rank, cand, near, cap in ranked:

        merged = False

        for i, (kr, kc, kn, kcap) in enumerate(kept):

            same_cap = _same_caption(cap, kcap)

            if _should_merge_bboxes(cand.bbox, kc.bbox):

                if rank > kr:

                    kept[i] = (rank, cand, near, cap or kcap)

                merged = True

                break

        if not merged:

            kept.append((rank, cand, near, cap))



    return [cand for _, cand, _, _ in kept]





def dedup_processed_tables(tables: list[ProcessedTable]) -> list[ProcessedTable]:

    if len(tables) <= 1:

        return list(tables)



    ranked = sorted(tables, key=_structure_rank_processed, reverse=True)

    kept: list[ProcessedTable] = []

    for tbl in ranked:

        merged = False

        for i, existing in enumerate(kept):

            same_cap = _same_caption(tbl.caption, existing.caption)

            if _should_merge_bboxes(tbl.bbox, existing.bbox):

                if _structure_rank_processed(tbl) > _structure_rank_processed(existing):

                    kept[i] = tbl

                merged = True

                break

        if not merged:

            kept.append(tbl)

    return kept


def dedup_one_per_caption(tables: list[ProcessedTable]) -> list[ProcessedTable]:
    """Keep the best-scoring table for each strict caption label on a page."""
    by_key: dict[str, ProcessedTable] = {}
    orphans: list[ProcessedTable] = []
    for tbl in tables:
        cap = (tbl.caption or "").strip().splitlines()
        key = cap[0].casefold() if cap else ""
        if not key:
            orphans.append(tbl)
            continue
        prev = by_key.get(key)
        if prev is None or _structure_rank_processed(tbl) > _structure_rank_processed(prev):
            by_key[key] = tbl
    return list(by_key.values()) + orphans


