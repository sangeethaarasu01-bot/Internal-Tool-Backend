"""Verify abstract text for SMTFL extraction job."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from bson import ObjectId
from lxml import etree
from pymongo import MongoClient

from app.services.extraction_workflow import apply_scope_to_extraction
from app.services.ir_semantic_adapter import ir_to_semantic_mapping
from app.services.xml_generator import generate_jats_xml

EID = os.environ.get("TRACE_EXTRACTION_ID", "6acbaa73d6c6114928772798")


def main() -> None:
    doc = MongoClient(os.environ["MONGODB_URI"])["ieee_converter"]["extractions"].find_one(
        {"_id": ObjectId(EID)}
    )
    blocks = doc["result"]["structure"]["blocks"]
    path = (doc.get("template") or {}).get("file_path")
    schema = (doc.get("template") or {}).get("template_schema")
    scope = apply_scope_to_extraction(scope="full", result=doc["result"], template_schema=schema)
    mapping = ir_to_semantic_mapping(scope["filtered_ir"], processed_blocks=blocks)
    xml = generate_jats_xml(path, mapping)
    root = etree.fromstring(xml.encode("utf-8"))
    abstract = "".join(root.xpath("//*[local-name()='abstract']//text()"))
    abstract = " ".join(abstract.split())
    print("START:", abstract[:80])
    print("This 1.80 bug:", "This 1.80" in abstract)
    print("gap bug:", "approximately state-of-the-art" in abstract.lower())
    print("good mid:", "approximately 1.80%, significantly outperforming state-of-the-art" in abstract)
    print("END:", abstract[-90:])


if __name__ == "__main__":
    main()
