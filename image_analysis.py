import fitz

PDF = r"C:\Users\ponar\Downloads\9798216211488_web.pdf"
doc = fitz.open(PDF)

for page_num in [1, 5, 9, 50, 100, 142]:
    if page_num <= len(doc):
        page = doc[page_num - 1]
        imgs = page.get_images(full=True)
        print(f"=== Page {page_num} ({len(imgs)} images) ===")
        for i, img in enumerate(imgs):
            xref = img[0]
            try:
                base = doc.extract_image(xref)
                w = base["width"]
                h = base["height"]
                size = len(base["image"])
                ext = base["ext"]
                print(f"  [{i+1}] {w}x{h} px | {size} bytes | {ext}")
            except Exception as e:
                print(f"  [{i+1}] ERROR: {e}")
        print()