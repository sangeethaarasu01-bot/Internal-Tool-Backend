import logging
from datetime import datetime, timezone

from app.database import conversions_col
from app.services.ieee_jats import generate_ieee_jats
from app.services.pdf_extractor import extract_paper
from bson import ObjectId

logger = logging.getLogger(__name__)


def process_pdf(conversion_id: str, file_path: str) -> None:
    col = conversions_col()
    oid = ObjectId(conversion_id)

    col.update_one(
        {"_id": oid},
        {"$set": {"status": "processing", "error_message": None}},
    )

    try:
        logger.info("Processing PDF %s", file_path)
        paper = extract_paper(file_path)
        xml_content = generate_ieee_jats(paper)
        col.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "completed",
                    "xml_content": xml_content,
                    "page_count": paper.page_count,
                    "title": paper.title,
                    "doi": paper.doi,
                    "completed_at": datetime.now(timezone.utc),
                    "error_message": None,
                }
            },
        )
        logger.info("Conversion %s completed", conversion_id)
    except Exception as exc:
        logger.exception("Conversion %s failed", conversion_id)
        col.update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
