"""
Direct PDF extraction test — verifies text, images, tables, and equations.
"""
import sys
from pathlib import Path

PDF_PATH = r"C:\Users\ponar\Downloads\9798216211488_web.pdf"

print(f"PDF Path: {PDF_PATH}")
p = Path(PDF_PATH)
print(f"Exists:   {p.exists()}")
if not p.exists():
    print("ERROR: PDF not found. Check the path.")
    sys.exit(1)
print(f"Size:     {p.stat().st_size / 1024 / 1024:.2f} MB")
print()

# ─────────────────────────────────────
# 1. PyMuPDF (text + images)
# ─────────────────────────────────────
print("=" * 60)
print("1. PyMuPDF (fitz) — text + images")
print("=" * 60)
try:
    import fitz
    doc = fitz.open(PDF_PATH)
    print(f"Pages: {len(doc)}")
    
    total_text = 0
    total_images = 0
    for i, page in enumerate(doc):
        t = page.get_text()
        total_text += len(t)
        total_images += len(page.get_images())
    
    print(f"Total text chars: {total_text:,}")
    print(f"Total images:     {total_images}")
    print(f"Page 1 sample:    {doc[0].get_text()[:200]!r}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
print()

# ─────────────────────────────────────
# 2. pdfplumber — text + tables
# ─────────────────────────────────────
print("=" * 60)
print("2. pdfplumber — text + tables")
print("=" * 60)
try:
    import pdfplumber
    with pdfplumber.open(PDF_PATH) as pdf:
        print(f"Pages: {len(pdf.pages)}")
        total_tables = 0
        total_text = 0
        for page in pdf.pages:
            total_text += len(page.extract_text() or "")
            total_tables += len(page.extract_tables() or [])
        print(f"Total text chars: {total_text:,}")
        print(f"Total tables:     {total_tables}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
print()

# ─────────────────────────────────────
# 3. Math/equation extraction (pix2tex or similar)
# ─────────────────────────────────────
print("=" * 60)
print("3. Math/equation extraction check")
print("=" * 60)
try:
    # Check what math library is available
    try:
        from pix2tex.cli import LatexOCR
        print("Math extractor: pix2tex (LatexOCR) available")
    except ImportError:
        print("pix2tex not installed")
    try:
        import latex2mathml
        print("latex2mathml available")
    except ImportError:
        print("latex2mathml not installed")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
print()

# ─────────────────────────────────────
# 4. PIL/Pillow check (for image processing)
# ─────────────────────────────────────
print("=" * 60)
print("4. PIL/Pillow check")
print("=" * 60)
try:
    from PIL import Image
    print(f"Pillow: OK")
except Exception as e:
    print(f"FAIL: {e}")
print()

print("=" * 60)
print("DONE")
print("=" * 60)