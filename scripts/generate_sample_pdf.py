"""Generate IEEE-style sample PDF for local testing."""

from pathlib import Path

import pymupdf as fitz

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
SAMPLES.mkdir(parents=True, exist_ok=True)
OUT = SAMPLES / "access-khan-3639184-proof1.pdf"

TITLE = "Deep Learning for Breast Cancer Diagnosis Using Mammography"
AUTHORS = "John A. Smith, Maria B. Lee, Chen X. Wei, Priya N. Nair, David O. Brown"
AFFIL = "1Department of Radiology, Example University, City, Country"
ABSTRACT = (
    "ABSTRACT This paper presents a deep learning approach for breast cancer diagnosis. "
    "We evaluate convolutional neural networks on mammography datasets with strong results."
)
KEYWORDS = "INDEX TERMS Breast cancer, deep learning, mammography, diagnosis"
SECTIONS = [
    "I. INTRODUCTION",
    "Breast cancer remains a leading cause of mortality. Automated diagnosis can assist radiologists.",
    "II. RELATED WORK",
    "Prior work explored machine learning for medical imaging.",
    "III. METHODOLOGY",
    "We describe our network architecture and training procedure.",
    "IV. EXPERIMENTS",
    "We report accuracy and AUC on held-out data.",
    "V. RESULTS",
    "Our model achieves competitive performance.",
    "VI. DISCUSSION",
    "We discuss limitations and future work.",
    "VII. CONCLUSION",
    "We conclude with summary remarks.",
    "REFERENCES",
    "[1] A. Author, Sample Journal, vol. 1, pp. 1-10, 2020.",
    "[2] B. Writer, Another Source, vol. 2, pp. 11-20, 2021.",
    "[3] C. Researcher, Conference Proc., pp. 100-110, 2019.",
]


def main() -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    page.insert_text((72, y), TITLE, fontsize=16)
    y += 28
    y += 22
    page.insert_text((72, y), AUTHORS, fontsize=11)
    y += 18
    page.insert_text((72, y), AFFIL, fontsize=10)
    y += 24
    for line in (ABSTRACT, KEYWORDS):
        page.insert_text((72, y), line, fontsize=10)
        y += 40
    for line in SECTIONS:
        if y > 780:
            page = doc.new_page(width=595, height=842)
            y = 72
        page.insert_text((72, y), line, fontsize=10)
        y += 16
    doc.save(str(OUT))
    doc.close()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
