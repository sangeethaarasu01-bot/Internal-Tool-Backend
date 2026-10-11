import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from bson import ObjectId
from pymongo import MongoClient
from app.utils.front_matter_recovery import coerce_processed_blocks
from app.utils.text_utils import merge_block_texts

doc = MongoClient(os.environ["MONGODB_URI"])["ieee_converter"]["extractions"].find_one(
    {"_id": ObjectId("6acbaa73d6c6114928772798")}
)
blocks = coerce_processed_blocks(doc["result"]["structure"]["blocks"])
p1 = sorted(
    [b for b in blocks if b.page_number == 1 and not b.exclude_from_content],
    key=lambda b: b.reading_order_index,
)
for b in p1:
    if 8 <= b.reading_order_index <= 56:
        t = (b.text or "")[:55]
        print(f"{b.reading_order_index:3} {b.block_id:8} {str(b.column):10} {t!r}")

subset = [b for b in p1 if 8 <= b.reading_order_index <= 53]
merged = merge_block_texts([b.text or "" for b in subset])
print("1.80%", "1.80%" in merged)
print("gap", "approximately state-of-the-art" in merged)
print("end", merged[-80:])
