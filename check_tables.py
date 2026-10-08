import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/output_test.json"

with open(path, "r", encoding="utf-8") as f:
    d = json.load(f)

print(f"File: {path}")
print(f"table_count: {d.get('table_count', '?')}")
print(f"timestamp: {d.get('extraction_timestamp', '?')}")
print(f"page_count: {d.get('page_count', '?')}")
print()
print(f"{'ID':<12} | {'Page':<5} | {'Size':<8} | {'Caption'}")
print("-" * 90)
for t in d.get("tables", []):
    caption = (t.get("caption") or "NO CAPTION")[:60]
    size = f"{t['row_count']}x{t['column_count']}"
    print(f"{t['table_id']:<12} | p{t['page_number']:<4} | {size:<8} | {caption}")
    headers = t.get("headers") or []
    rows = t.get("rows") or []
    preview = []
    if headers:
        preview.append(headers)
    preview.extend(rows[: max(0, 2 - len(preview))])
    for row in preview[:2]:
        print(f"             {' | '.join(str(c)[:70] for c in row)}")