import fitz

doc = fitz.open(r"C:\Users\ponar\Downloads\9798216211488_web.pdf")

for p in [13, 30, 50, 78, 98, 130]:
    page = doc[p-1]
    text = page.get_text()
    idx = text.lower().find("table")
    if idx >= 0:
        print(f"=== Page {p} (context around 'table') ===")
        print(text[max(0, idx-150):idx+250])
        print("-" * 60)