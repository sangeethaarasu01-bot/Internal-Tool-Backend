"""DocBook 5.0 chapter-level chunking and Mongo-safe storage."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from app.services.docbook_book_chunking import (
    chunk_docbook_book_xml,
    reassemble_book_xml_from_chunks,
)
from app.services.docbook_book_storage import (
    STORAGE_MODE_CHUNKED,
    generated_xml_record_for_chunked_book,
    retry_failed_chapters,
    write_book_chunks,
)
from app.services.mongo_bson_limits import MONGODB_MAX_BSON_DOCUMENT_BYTES, mongodb_max_payload_bytes
from app.services.template_format import DOCBOOK_NS

ROOT = Path(__file__).resolve().parent
MINIMAL = ROOT / "fixtures" / "minimal_docbook_book.xml"
LARGE_CHAPTER = ROOT / "fixtures" / "docbook_large_chapter.xml"


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def replace_one(self, filter: dict, doc: dict, upsert: bool = False) -> None:
        self.docs[doc["_id"]] = doc

    def find(self, query: dict):
        ext = query.get("extraction_id")
        return [d for d in self.docs.values() if d.get("extraction_id") == ext]

    def count_documents(self, query: dict) -> int:
        return len(list(self.find(query)))


def test_mongodb_limit_is_sixteen_mebibytes() -> None:
    assert MONGODB_MAX_BSON_DOCUMENT_BYTES == 16 * 1024 * 1024
    assert mongodb_max_payload_bytes() < MONGODB_MAX_BSON_DOCUMENT_BYTES


def test_minimal_book_manifest_metadata_and_order() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    manifest, chunks = chunk_docbook_book_xml(xml, extraction_id="ext-1")
    assert manifest.book_id == "10.0000/testbook"
    assert manifest.title == "Test Book"
    assert manifest.authors == ["Ada Lovelace", "Grace Hopper"]
    assert manifest.doi == "10.0000/testbook"
    assert manifest.source_document_format == "docbook_5"
    sequences = [c.sequence for c in chunks]
    assert sequences == sorted(sequences)
    kinds = [c.kind for c in chunks]
    assert "preface" in kinds
    assert "chapter" in kinds
    assert chunks[-1].kind == "chapter"
    assert all(c.payload_bytes <= mongodb_max_payload_bytes() for c in chunks)


def test_front_matter_and_chapter_ids_follow_book_id() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    manifest, chunks = chunk_docbook_book_xml(xml, extraction_id="ext-1")
    for chunk in chunks:
        assert chunk.document_id.startswith(manifest.book_id)


def test_section_split_when_payload_cap_low() -> None:
    xml = LARGE_CHAPTER.read_text(encoding="utf-8")
    manifest, chunks = chunk_docbook_book_xml(
        xml,
        extraction_id="ext-large",
        max_payload_bytes=400,
    )
    assert manifest.book_id == "10.5040/9798216520177"
    split = [c for c in chunks if c.split_parent_id]
    assert len(split) >= 2
    for chunk in split:
        assert chunk.payload_bytes <= 400
        root = etree.fromstring(chunk.xml_fragment.encode("utf-8"))
        assert root.tag == f"{{{DOCBOOK_NS}}}chapter"


def test_reassemble_round_trip_minimal() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    manifest, chunks = chunk_docbook_book_xml(xml, extraction_id="ext-1")
    by_id = {c.document_id: c.xml_fragment for c in chunks}
    rebuilt = reassemble_book_xml_from_chunks(manifest.to_dict(), by_id)
    root = etree.fromstring(rebuilt.encode("utf-8"))
    assert root.tag == f"{{{DOCBOOK_NS}}}book"
    text = etree.tostring(root, encoding="unicode")
    assert "Chapter One" in text
    assert "Front matter text." in text


def test_write_chunks_idempotent() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    col = _FakeCollection()
    first = write_book_chunks("ext-a", xml, col=col)
    assert first.all_ok
    count_first = col.count_documents({"extraction_id": "ext-a"})
    second = write_book_chunks("ext-a", xml, col=col)
    assert second.all_ok
    assert col.count_documents({"extraction_id": "ext-a"}) == count_first


@pytest.fixture
def fake_col() -> _FakeCollection:
    return _FakeCollection()


def test_generated_record_has_no_inline_book_xml() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    col = _FakeCollection()
    write_result = write_book_chunks("ext-b", xml, col=col)
    record = generated_xml_record_for_chunked_book(
        scope="full",
        mapping_source="ir_adapter",
        prompt_version=None,
        warnings=[],
        manifest=write_result.manifest,
        write_result=write_result,
    )
    assert record["storage_mode"] == STORAGE_MODE_CHUNKED
    assert record["xml_content"] is None
    assert record["chapter_write_ok"] is True
    assert record["book_manifest"]["total_unit_count"] >= 2


def test_retry_failed_chapters_only_rewrites_failed() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    col = _FakeCollection()
    write_result = write_book_chunks("ext-c", xml, col=col)
    manifest = write_result.manifest
    first_id = manifest["units"][0]["document_id"]
    manifest["units"][0]["status"] = "failed"
    retry = retry_failed_chapters("ext-c", xml, manifest)
    assert retry.all_ok
    retried_ids = {w.document_id for w in retry.writes}
    assert retried_ids == {first_id}


def test_large_book_fixture_chunk_count_and_payload_cap() -> None:
    book_path = ROOT.parent / "data" / "outputs" / "d459ad96-bf30-41a4-98ab-04c08d4f8b27.xml"
    if not book_path.is_file():
        pytest.skip("large DocBook integration fixture not present")
    xml = book_path.read_text(encoding="utf-8")
    manifest, chunks = chunk_docbook_book_xml(xml, extraction_id="integration-book")
    assert manifest.total_unit_count == len(chunks)
    assert manifest.total_unit_count >= 10
    cap = mongodb_max_payload_bytes()
    assert all(c.payload_bytes <= cap for c in chunks)


def test_hierarchy_lists_part_and_children() -> None:
    xml = MINIMAL.read_text(encoding="utf-8")
    manifest, _ = chunk_docbook_book_xml(xml, extraction_id="ext-1")
    hierarchy = manifest.hierarchy
    parts = [n for n in hierarchy if n["kind"] == "part"]
    assert parts
    part_id = parts[0]["node_id"]
    assert any(n.get("parent_id") == part_id for n in hierarchy)
