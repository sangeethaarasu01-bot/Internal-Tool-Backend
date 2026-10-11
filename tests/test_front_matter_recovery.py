from app.models.document_structure import ProcessedBlock
from app.services.layout.semantic_builder import _can_merge_title
from app.utils.front_matter_recovery import (
    parse_index_terms_keywords,
    recover_article_title,
)

AMARA_TITLE = (
    "Split Multi-Task Federated Learning for Battery Health and "
    "Capacity Estimation in Electric Vehicles"
)


def _block(
    page: int,
    text: str,
    *,
    order: int,
    size: float = 14.0,
    excluded: bool = False,
) -> ProcessedBlock:
    return ProcessedBlock(
        block_id=f"p{page}b{order}",
        page_number=page,
        reading_order_index=order,
        column="FULL_WIDTH",
        classification="PARAGRAPH",
        exclude_from_content=excluded,
        exclusion_reason="author_queries_cover" if excluded else None,
        bbox=[0.0, float(order * 20), 500.0, float(order * 20 + 18)],
        text=text,
        block_type="text",
        dominant_font_size=size,
    )


def test_parse_index_terms_strips_prefix_and_keeps_phrases() -> None:
    raw = (
        "Index Terms— Electric vehicle, battery state of health, "
        "state of charge, federated learning"
    )
    keywords = parse_index_terms_keywords(raw)
    assert keywords[0] == "Electric vehicle"
    assert "battery state of health" in keywords
    assert any("charge" in item for item in keywords)


def test_recover_title_after_proof_cover_page() -> None:
    processed = [
        _block(1, "AUTHOR QUERIES\nAQ: 1 please answer", order=0, excluded=True),
        _block(2, "IEEE Transactions on Consumer Electronics", order=0, size=10.0),
        _block(2, AMARA_TITLE, order=1, size=16.0),
        _block(2, "Abdelaziz Amara Korba", order=2, size=11.0),
        _block(2, "Abstract— The rapid adoption", order=3, size=10.0),
    ]
    recovered = recover_article_title(
        processed,
        title_threshold=15.0,
        can_merge_title=_can_merge_title,
    )
    assert recovered is not None
    title, _blocks, _confidence = recovered
    assert "Split Multi-Task Federated Learning" in title
