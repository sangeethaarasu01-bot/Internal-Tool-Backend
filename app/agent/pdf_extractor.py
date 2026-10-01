"""Stage 2: extract structured content from IEEE PDF."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path

import pymupdf as fitz
import pdfplumber

from app.config import settings
from app.agent.layout_paper_adapter import extract_paper_via_layout
from app.llm.client import LLMClient
from app.utils.logger import logger
from app.utils.paper_sanitize import sanitize_paper_data
from app.utils.xml_helpers import clean_extracted_abstract
from app.models.paper import (
    Affiliation,
    Author,
    Equation,
    Figure,
    PaperData,
    Reference,
    Section,
    Table,
)

MAIN_SEC = re.compile(r"^([IVXLC]+)\.\s+(.+)$", re.IGNORECASE)
NUM_MAIN_SEC = re.compile(r"^(\d+)\.\s+(.+)$")
SUB_SEC = re.compile(r"^([A-Z])\.\s+([A-Z][A-Za-z\s&]+)$")
SUBSUB_SEC = re.compile(r"^(\d+)\)\s+([A-Z][A-Za-z\s]+)$")
REF_SPLIT = re.compile(r"^\s*\[(\d+)\]", re.MULTILINE)
FIG_CAP = re.compile(r"FIGURE\s+(\d+)\.\s+(.+?)(?=FIGURE|\Z)", re.DOTALL | re.IGNORECASE)
EQ_LINE = re.compile(r"(.+?)\s*\((\d+)\)\s*$")


class PDFExtractor:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def _page_text_blocks(self, doc: fitz.Document) -> list[str]:
        lines: list[str] = []
        for page_num in range(min(len(doc), settings.MAX_PDF_PAGES)):
            page = doc[page_num]
            blocks = page.get_text("blocks")
            blocks.sort(key=lambda b: (round(b[1] / 10), b[0]))
            mid = page.rect.width / 2
            left = [b for b in blocks if b[0] < mid]
            right = [b for b in blocks if b[0] >= mid]
            for group in (left, right):
                for b in sorted(group, key=lambda x: (x[1], x[0])):
                    text = b[4].strip()
                    if text:
                        lines.extend(text.splitlines())
        return lines

    def _is_title_page_noise(self, text: str) -> bool:
        t = text.strip()
        if not t or re.fullmatch(r"\d{1,4}", t):
            return True
        upper = t.upper()
        if "IEEE" in upper and any(k in upper for k in ("JOURNAL", "SENSORS", "ACCESS", "TRANSACTIONS")):
            return True
        if "SENSORS COUNCIL" in upper or upper.startswith("VOL."):
            return True
        if upper in {"RESEARCH ARTICLE", "LETTER", "COMMUNICATION"}:
            return True
        return False

    def _looks_like_author_line(self, text: str, font_size: float, title_size: float) -> bool:
        if re.search(r"Member,\s*IEEE", text, re.I):
            return True
        if "ORCID" in text.upper():
            return True
        # Author lines are usually smaller than the title block
        if font_size < title_size - 1.0 and re.search(
            r"[A-Z][a-z\-]+\s+[A-Z][a-z\-]+", text
        ):
            names = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z\-]+", text)
            if len(names) >= 2:
                return True
        return False

    def _extract_title(self, doc: fitz.Document) -> str:
        """Merge multi-line IEEE titles (same large font on page 1)."""
        page = doc[0]
        line_rows: list[tuple[float, float, float, str]] = []

        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(s.get("text", "") for s in spans).strip()
                text = re.sub(r"\s+", " ", text)
                if len(text) < 3 or self._is_title_page_noise(text):
                    continue
                max_size = max(float(s.get("size", 0)) for s in spans)
                y0 = float(line["bbox"][1])
                x0 = float(line["bbox"][0])
                line_rows.append((y0, max_size, x0, text))

        if not line_rows:
            return ""

        max_size = max(sz for _, sz, _, _ in line_rows)
        size_tol = 1.75
        page_h = float(page.rect.height)

        candidates: list[tuple[float, str]] = []
        for y0, sz, _x0, text in sorted(line_rows, key=lambda r: r[0]):
            if y0 > page_h * 0.52:
                break
            if sz < max_size - size_tol:
                if candidates:
                    break
                continue
            if self._looks_like_author_line(text, sz, max_size):
                break
            if re.search(r"^Abstract\b", text, re.I):
                break
            candidates.append((y0, text))

        if not candidates:
            # Fallback: single largest line
            line_rows.sort(key=lambda r: (-r[1], r[0]))
            return line_rows[0][3]

        parts: list[str] = []
        prev_y = -1.0
        for y0, text in candidates:
            if prev_y >= 0 and y0 - prev_y > 28:
                break
            parts.append(text)
            prev_y = y0

        title = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return title

    def _extract_abstract_keywords(self, full_text: str) -> tuple[str, list[str]]:
        abstract = ""
        keywords: list[str] = []
        m = re.search(
            r"ABSTRACT\s*(.+?)(?:INDEX\s+TERMS|Keywords|I\.\s+INTRODUCTION)",
            full_text,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            abstract = clean_extracted_abstract(m.group(1))
        km = re.search(
            r"INDEX\s+TERMS\s*[—\-:]?\s*(.+?)(?:I\.\s+INTRODUCTION|\n\n)",
            full_text,
            re.DOTALL | re.IGNORECASE,
        )
        if km:
            raw = km.group(1).replace("\n", " ")
            keywords = [k.strip() for k in re.split(r"[;,]", raw) if k.strip()]
        return abstract, keywords

    _NOT_AUTHOR_TOKENS = re.compile(
        r"\b(?:books?|publishing|boulevard|road|street|press|united kingdom|"
        r"lexington|littlefield|rowman|forbes|thornbury|isbn|library of congress|"
        r"printed in)\b",
        re.I,
    )

    def _is_plausible_author_name(self, name: str) -> bool:
        if self._NOT_AUTHOR_TOKENS.search(name):
            return False
        parts = name.split()
        if len(parts) < 2:
            return False
        if parts[0].lower() in {"new", "the", "united", "san", "los"}:
            return False
        return True

    def _is_library_catalog_line(self, line: str) -> bool:
        if re.search(r"library of congress|isbn|dc\d{2}|--dc\d{2}|ANSI/NISO", line, re.I):
            return True
        if re.search(r"\d{3,}\s*--\s*[A-Z]{2,}", line):
            return True
        return False

    def _line_is_title_fragment(self, line: str, title: str) -> bool:
        line_s = re.sub(r"\s+", " ", line.strip())
        title_s = re.sub(r"\s+", " ", title.strip())
        if not line_s or not title_s:
            return False
        if line_s == title_s:
            return True
        if line_s in title_s:
            return True
        return False

    def _extract_authors_affiliations(
        self, lines: list[str], title: str = ""
    ) -> tuple[list[Author], list[Affiliation]]:
        authors: list[Author] = []
        affiliations: list[Affiliation] = []
        author_block: list[str] = []
        for line in lines[:40]:
            if re.search(r"ABSTRACT", line, re.I):
                break
            if title and self._line_is_title_fragment(line, title):
                continue
            if len(line) > 160:
                continue
            if re.search(r"Department|University|Institute|Laboratory", line, re.I):
                continue
            author_block.append(line)
        text = " ".join(author_block)
        names = re.findall(
            r"([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z\-]+)(?:\s*[\d,*]+)?",
            text,
        )
        names = [n for n in names if self._is_plausible_author_name(n)]
        email_m = re.search(r"[\w.\-]+@[\w.\-]+\.\w+", text)
        email = email_m.group(0) if email_m else None
        for idx, name in enumerate(names[:10]):
            parts = name.split()
            authors.append(
                Author(
                    first_name=parts[0] if parts else "",
                    last_name=parts[-1] if len(parts) > 1 else "",
                    full_name=name.strip(),
                    email=email if idx == 0 else None,
                    corresponding=idx == 0 and email is not None,
                    affiliation_refs=["aff1"],
                )
            )
        if authors:
            affiliations.append(Affiliation(id="aff1", institution="See PDF for affiliation details"))
        return authors, affiliations

    def _build_sections(self, lines: list[str]) -> list[Section]:
        sections: list[Section] = []
        current: Section | None = None
        current_sub: Section | None = None
        para_buf: list[str] = []
        sec_id = 0

        def flush_para(target: Section | None) -> None:
            if target and para_buf:
                target.paragraphs.append(" ".join(para_buf).strip())
                para_buf.clear()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if re.search(r"^REFERENCES$", line, re.I):
                flush_para(current_sub or current)
                break
            if self._is_library_catalog_line(line):
                continue
            m_main = MAIN_SEC.match(line) or NUM_MAIN_SEC.match(line)
            m_sub = SUB_SEC.match(line)
            m_subsub = SUBSUB_SEC.match(line)
            if m_main and not self._is_library_catalog_line(m_main.group(2)):
                flush_para(current_sub or current)
                sec_id += 1
                label = m_main.group(1)
                if NUM_MAIN_SEC.match(line):
                    label = f"{label}."
                else:
                    label = f"{label.upper()}."
                current = Section(
                    id=f"sec{sec_id}",
                    label=label,
                    title=m_main.group(2).strip(),
                    level=1,
                )
                current_sub = None
                sections.append(current)
                continue
            if m_sub and current:
                flush_para(current_sub or current)
                sec_id += 1
                current_sub = Section(
                    id=f"sec{sec_id}",
                    label=f"{m_sub.group(1)}.",
                    title=m_sub.group(2).strip(),
                    level=2,
                )
                current.subsections.append(current_sub)
                continue
            if m_subsub and (current_sub or current):
                flush_para(current_sub or current)
                sec_id += 1
                sub = Section(
                    id=f"sec{sec_id}",
                    label=f"{m_subsub.group(1)})",
                    title=m_subsub.group(2).strip(),
                    level=3,
                )
                parent = current_sub or current
                if parent:
                    parent.subsections.append(sub)
                current_sub = sub
                continue
            if current_sub or current:
                para_buf.append(line)

        flush_para(current_sub or current)
        return sections

    def _fallback_sections(self, full_text: str) -> list[Section]:
        """When heading patterns fail, pull body text after abstract/introduction."""
        ref_m = re.search(r"\bREFERENCES\b", full_text, re.I)
        end = ref_m.start() if ref_m else len(full_text)
        start = 0
        for pat in (
            r"(?:^|\n)\s*I\.\s+INTRODUCTION\b",
            r"(?:^|\n)\s*1\.\s+Introduction\b",
            r"(?:^|\n)\s*1\.\s+INTRODUCTION\b",
            r"(?:^|\n)\s*INTRODUCTION\b",
        ):
            m = re.search(pat, full_text, re.I)
            if m:
                start = m.end()
                break
        if not start:
            am = re.search(r"\bABSTRACT\b", full_text, re.I)
            if am:
                start = am.end()
        chunk = full_text[start:end]
        if len(chunk.strip()) < 80:
            return []
        paras: list[str] = []
        buf: list[str] = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                if buf:
                    paras.append(re.sub(r"\s+", " ", " ".join(buf)).strip())
                    buf.clear()
                continue
            if MAIN_SEC.match(line) or NUM_MAIN_SEC.match(line) or SUB_SEC.match(line):
                if buf:
                    paras.append(re.sub(r"\s+", " ", " ".join(buf)).strip())
                    buf.clear()
                continue
            if len(line) > 8:
                buf.append(line)
        if buf:
            paras.append(re.sub(r"\s+", " ", " ".join(buf)).strip())
        paras = [p for p in paras if len(p) >= 40][:40]
        if not paras:
            return []
        return [
            Section(
                id="sec1",
                title="Introduction",
                level=1,
                paragraphs=paras,
            )
        ]

    def _extract_references(self, full_text: str) -> list[Reference]:
        refs: list[Reference] = []
        idx = re.search(r"\bREFERENCES\b", full_text, re.I)
        if not idx:
            return refs
        tail = full_text[idx.end() :]
        parts = REF_SPLIT.split(tail)
        if len(parts) < 2:
            return refs
        for i in range(1, len(parts), 2):
            num = int(parts[i])
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            body = re.sub(r"\s+", " ", body)[:2000]
            if body:
                refs.append(Reference(id=f"ref{num}", number=num, raw_text=body))
        return refs

    def _extract_figures(
        self,
        doc: fitz.Document,
        full_text: str,
        job_dir: Path | None,
        *,
        light: bool = False,
    ) -> list[Figure]:
        figures: list[Figure] = []
        for m in FIG_CAP.finditer(full_text):
            num = int(m.group(1))
            cap = m.group(2).strip()[:500]
            img_path = None
            if not light and job_dir:
                job_dir.mkdir(parents=True, exist_ok=True)
                for page in doc:
                    if img_path:
                        break
                    for img_index, img in enumerate(page.get_images(full=True)):
                        try:
                            pix = fitz.Pixmap(doc, img[0])
                            if pix.n - pix.alpha < 4:
                                out = job_dir / f"fig{num}_{img_index}.png"
                                pix.save(str(out))
                                img_path = str(out)
                                break
                        except Exception:
                            continue
            figures.append(
                Figure(
                    id=f"fig{num}",
                    number=num,
                    caption=cap,
                    image_path=img_path,
                    suggested_filename=f"figure{num}.eps",
                )
            )
        return figures

    def _extract_tables(self, pdf_path: Path, full_text: str) -> list[Table]:
        tables: list[Table] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages[: settings.MAX_PDF_PAGES]):
                for t_idx, raw in enumerate(page.extract_tables() or []):
                    if not raw:
                        continue
                    num = len(tables) + 1
                    tables.append(
                        Table(
                            id=f"table{num}",
                            number=num,
                            title=f"Table {num}",
                            rows=[[cell or "" for cell in row] for row in raw],
                            caption=f"Table on page {page_num + 1}",
                        )
                    )
        return tables

    def _extract_equations(self, lines: list[str]) -> list[Equation]:
        eqs: list[Equation] = []
        for line in lines:
            m = EQ_LINE.match(line.strip())
            if m:
                num = int(m.group(2))
                eqs.append(Equation(id=f"deqn{num}", number=num, latex=m.group(1).strip()))
        return eqs

    def _attach_assets(
        self, paper: PaperData, pdf_path: Path, job_id: str | None
    ) -> PaperData:
        """Figures/tables/equations from legacy helpers (layout path focuses on text)."""
        doc = fitz.open(str(pdf_path))
        try:
            lines = self._page_text_blocks(doc)
            full_text = "\n".join(lines)
            job_dir = settings.uploads_dir / job_id if job_id else None
            light = settings.LIGHT_PDF_EXTRACT
            figures = self._extract_figures(doc, full_text, job_dir, light=light)
            tables: list[Table] = []
            if not light:
                tables = self._extract_tables(pdf_path, full_text)
            equations = self._extract_equations(lines)
            meta = dict(paper.metadata)
            meta.setdefault("source_filename", pdf_path.name)
            msid_m = re.search(r"(\d{6,})", pdf_path.name)
            if msid_m:
                meta.setdefault("manuscript_id", msid_m.group(1))
            doi_m = re.search(r"10\.\d{4,}/[^\s]+", full_text)
            if doi_m:
                meta.setdefault("doi", doi_m.group(0))
            return paper.model_copy(
                update={
                    "figures": figures,
                    "tables": tables,
                    "equations": equations,
                    "metadata": meta,
                }
            )
        finally:
            doc.close()

    async def extract(
        self,
        pdf_path: Path,
        on_event: Callable[[dict], None] | None = None,
        job_id: str | None = None,
    ) -> PaperData:
        if on_event:
            on_event({"type": "log", "message": f"Opening PDF {pdf_path.name}"})
        return await asyncio.to_thread(self._extract_sync, pdf_path, job_id)

    def _extract_sync(self, pdf_path: Path, job_id: str | None) -> PaperData:
        try:
            layout_paper = extract_paper_via_layout(pdf_path)
            layout_paper = self._attach_assets(layout_paper, pdf_path, job_id)
            return sanitize_paper_data(layout_paper)
        except Exception as exc:
            logger.warning("Layout PDF extraction failed ({}), using legacy heuristics", exc)

        doc = fitz.open(str(pdf_path))
        try:
            lines = self._page_text_blocks(doc)
            full_text = "\n".join(lines)
            title = self._extract_title(doc)
            if not title and lines:
                for line in lines[:15]:
                    if len(line) > 20 and "ABSTRACT" not in line.upper():
                        title = line
                        break

            abstract, keywords = self._extract_abstract_keywords(full_text)
            authors, affiliations = self._extract_authors_affiliations(lines, title=title)
            sections = self._build_sections(lines)
            references = self._extract_references(full_text)
            job_dir = settings.uploads_dir / job_id if job_id else None
            light = settings.LIGHT_PDF_EXTRACT
            figures = self._extract_figures(doc, full_text, job_dir, light=light)
            tables: list[Table] = []
            if not light:
                tables = self._extract_tables(pdf_path, full_text)
            equations = self._extract_equations(lines)

            msid_m = re.search(r"(\d{6,})", pdf_path.name)
            metadata = {
                "manuscript_id": msid_m.group(1) if msid_m else "",
                "source_filename": pdf_path.name,
            }
            doi_m = re.search(r"10\.\d{4,}/[^\s]+", full_text)
            if doi_m:
                metadata["doi"] = doi_m.group(0)

            warnings: list[str] = []
            if not abstract:
                warnings.append("Abstract not detected; check PDF layout")
            if not sections:
                sections = self._fallback_sections(full_text)
                if sections:
                    warnings.append(
                        "Section headings not detected; body text taken from PDF after abstract/introduction",
                    )
                else:
                    warnings.append("No body sections extracted from PDF; output body may be empty")
            if not title:
                warnings.append("PDF title not detected; check first page layout")
            if light:
                warnings.append(
                    "Light PDF mode: tables/figure images skipped (set LIGHT_PDF_EXTRACT=false locally for full extract)",
                )

            return sanitize_paper_data(
                PaperData(
                    title=title,
                    authors=authors,
                    affiliations=affiliations,
                    abstract=abstract,
                    keywords=keywords,
                    sections=sections,
                    references=references,
                    figures=figures,
                    tables=tables,
                    equations=equations,
                    metadata=metadata,
                    extraction_warnings=warnings,
                )
            )
        finally:
            doc.close()
