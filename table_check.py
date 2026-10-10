import fitz

PDF = r"C:\Users\ponar\Downloads\9798216211488_web.pdf"
doc = fitz.open(PDF)

# 1. Search for "table" keyword
print("=== 'TABLE' KEYWORD SEARCH ===")
hits = []
for i, page in enumerate(doc):
    t = page.get_text().lower()
    if "table" in t:
        hits.append(i + 1)
print(f"Pages with 'table': {len(hits)}")
if hits:
    print(f"  {hits[:20]}")

# 2. Vector drawing analysis (tables often drawn as many lines)
print()
print("=== VECTOR DRAWINGS (table indicator) ===")
for i, page in enumerate(doc):
    drawings = page.get_drawings()
    n = len(drawings)
    if n > 20:
        print(f"  Page {i+1}: {n} drawings")

# 3. Text distribution
print()
print("=== TEXT DISTRIBUTION ===")
with_text = 0
empty = 0
for page in doc:
    if page.get_text().strip():
        with_text += 1
    else:
        empty += 1
print(f"Pages with text: {with_text}/{len(doc)}")
print(f"Empty pages:    {empty}/{len(doc)}")