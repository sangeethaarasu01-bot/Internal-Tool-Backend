"""Author deduplication for IR adapter / JATS front matter."""

from __future__ import annotations

from app.models.semantic_mapping import MappedSemanticNode
from app.services.author_deduplication import (
    author_dedup_key,
    clean_author_display_name,
    deduplicate_author_names,
    deduplicate_mapped_authors,
)
from app.services.ir_semantic_adapter import ir_to_semantic_mapping


def test_clean_author_strips_superscript_and_broken_paren() -> None:
    assert clean_author_display_name("YUKI KAKICHI 1") == "YUKI KAKICHI"
    assert clean_author_display_name("Yuki Kakichi (kakichiyuki") == "Yuki Kakichi"


def test_dedupe_kakichi_corresponding_and_byline() -> None:
    names = deduplicate_author_names(
        [
            "Yuki Kakichi (kakichiyuki",
            "YUKI KAKICHI 1",
            "JOSCHKA SCHAUB 2",
            "ARNE MÜLLER 2",
        ]
    )
    keys = [author_dedup_key(n) for n in names]
    assert keys.count("yuki kakichi") == 1
    assert len(names) == 3
    assert any("Yuki" in n or "YUKI" in n for n in names)


def test_ir_adapter_dedupes_front_authors() -> None:
    ir = {
        "front": {
            "authors": [
                {
                    "type": "author",
                    "text": "Yuki Kakichi (kakichiyuki",
                    "elements": [{"type": "text", "value": "Yuki Kakichi (kakichiyuki"}],
                },
                {
                    "type": "author",
                    "text": "YUKI KAKICHI 1",
                    "elements": [{"type": "text", "value": "YUKI KAKICHI 1"}],
                },
                {
                    "type": "author",
                    "text": "JOSCHKA SCHAUB 2",
                    "elements": [{"type": "text", "value": "JOSCHKA SCHAUB 2"}],
                },
            ]
        },
        "body": {"sections": [], "loose_paragraphs": []},
        "back": {},
    }
    mapping = ir_to_semantic_mapping(ir)
    author_texts = [a.get("text", "") for a in mapping.front.get("authors", [])]
    assert len(author_texts) == 2
    assert author_dedup_key(author_texts[0]) == "yuki kakichi"


def test_deduplicate_mapped_authors_preserves_order() -> None:
    nodes = [
        MappedSemanticNode(semantic_type="author", text="YUKI KAKICHI 1"),
        MappedSemanticNode(semantic_type="author", text="JOSCHKA SCHAUB 2"),
    ]
    out = deduplicate_mapped_authors(nodes)
    assert [n.text for n in out] == ["YUKI KAKICHI", "JOSCHKA SCHAUB"]
