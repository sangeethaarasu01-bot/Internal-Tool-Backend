from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from bson import ObjectId

from app.services.data_retention import purge_expired_data


@patch("app.services.data_retention.conversions_col")
@patch("app.services.data_retention.book_documents_col")
@patch("app.services.data_retention.extractions_col")
@patch("app.services.data_retention.get_db")
def test_purge_deletes_old_extraction_disk_and_doc(
    mock_get_db,
    mock_ext_col,
    mock_book_col,
    mock_conv_col,
    tmp_path,
    monkeypatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    upload = tmp_path / "uploads" / "extractions"
    upload.mkdir(parents=True)
    pdf = upload / "old.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    oid = ObjectId()
    old = datetime.now(timezone.utc) - timedelta(days=5)
    doc = {
        "_id": oid,
        "filename": "old.pdf",
        "file_path": str(pdf),
        "status": "completed",
        "created_at": old,
    }
    ext_collection = MagicMock()
    ext_collection.find.return_value = [doc]
    mock_ext_col.return_value = ext_collection

    book_collection = MagicMock()
    book_collection.delete_many.return_value = MagicMock(deleted_count=2)
    mock_book_col.return_value = book_collection

    llm_collection = MagicMock()
    llm_collection.delete_many.return_value = MagicMock(deleted_count=1)
    mock_get_db.return_value = {"llm_calls": llm_collection}

    conv_collection = MagicMock()
    conv_collection.find.return_value = []
    mock_conv_col.return_value = conv_collection

    stats = purge_expired_data(retention_days=2)
    assert stats.extractions_deleted == 1
    assert stats.book_documents_deleted == 2
    assert stats.llm_calls_deleted == 1
    assert not pdf.exists()
    ext_collection.delete_one.assert_called_once_with({"_id": oid})
