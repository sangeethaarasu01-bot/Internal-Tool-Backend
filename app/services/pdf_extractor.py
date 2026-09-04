"""Extract structured IEEE-paper fields from a PDF for JATS mapping."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pymupdf

HEADER_NOISE = re.compile(
    r"(this article has been accepted|"
    r"authorized licensed|"
    r"digital object identifier|"
    r"content may change prior|"
    r"ieee xplore|"
    r"restrictions apply|"
    r"vol\.\s*\d+|"
    r"^\s*pp\.\s*\d+|"
    r"1530-437x|"
    r"1558-1748|"
    r"copyright|"
    r"personal use is permitted|"
    r"downloaded on)",
    re.I,
)

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;]+", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
ORCID_RE = re.compile(r"\b(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b", re.I)
ISSN_RE = re.compile(r"\b(\d{4}-\d{3}[\dXx])\b")
MAJOR_SEC_RE = re.compile(
    r"^(I{1,3}|IV|VI{0,3}|IX|X|XI{0,3}|XIV|XV|XVI{0,3}|XIX|XX)\.\s+([A-Z][A-Z0-9 \-/,&:()]+)$"
)
SUB_SEC_RE = re.compile(r"^([A-H])\.\s+([A-Z].+)$")
SUBSUB_SEC_RE = re.compile(r"^(\d+)\)\s+(.+)$")
FIG_RE = re.compile(r"^(?:Fig(?:ure)?\.?\s*)(\d+[a-z]?(?: and \d+)?)\.?\s*(.*)$", re.I)
TABLE_RE = re.compile(r"^(?:TABLE|Table)\s+([IVX\d]+)\.?\s*(.*)$")
REF_START_RE = re.compile(r"^(?:REFERENCES|References|BIBLIOGRAPHY)\s*$")
ABSTRACT_RE = re.compile(r"^(?:Abstract(?:[—–:\s-]*)|ABSTRACT(?:[—–:\s-]*))(.*)$", re.I)
INDEX_RE = re.compile(
    r"^(?:Index Terms|INDEX TERMS|Keywords|KEYWORDS)[—–:\s-]*(.*)$", re.I
)
DATE_RE = re.compile(
    r"(received|revised|accepted)\s+(?:on\s+)?(\d{1,2}\s+\w+\.?\s+\d{4}|\w+\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
MS_ID_RE = re.compile(r"\b([A-Z]{3,}[-_][A-Z0-9-]*\d{4,})\b")


@dataclass
class Author:
    given: str
    surname: str
    email: str = ""
    orcid: str = ""
    aff_ids: list[str] = field(default_factory=lambda: ["aff1"])
    corresp: bool = False
    ieee_member: str = ""


@dataclass
class Affiliation:
    id: str
    department: str = ""
    institution: str = ""
    city: str = ""
    post_code: str = ""
    country: str = ""
    raw: str = ""


@dataclass
class PaperSection:
    id: str
    label: str
    title: str
    paragraphs: list[str] = field(default_factory=list)
    figures: list[dict[str, str]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    children: list["PaperSection"] = field(default_factory=list)


@dataclass
class ExtractedPaper:
    title: str = "Untitled Article"
    journal_title: str = "IEEE Sensors Journal"
    journal_acronym: str = "JSEN"
    journal_id: str = "0055400"
    issn_print: str = "1530-437X"
    issn_online: str = "1558-1748"
    publisher: str = "IEEE"
    doi: str = ""
    manuscript_id: str = ""
    authors: list[Author] = field(default_factory=list)
    affiliations: list[Affiliation] = field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    history: dict[str, str] = field(default_factory=dict)
    sections: list[PaperSection] = field(default_factory=list)
    references: list[dict[str, str]] = field(default_factory=list)
    acknowledgement: str = ""
    page_count: int = 0
    fig_count: int = 0
    table_count: int = 0
    ref_count: int = 0
    source_filename: str = ""
    raw_text: str = ""


def extract_paper(pdf_path: str) -> ExtractedPaper:
    doc = pymupdf.open(pdf_path)
    paper = ExtractedPaper(page_count=len(doc), source_filename=pdf_path)

    page_texts: list[str] = []
    first_spans: list[dict] = []
    tables: list[dict[str, Any]] = []

    for i, page in enumerate(doc):
        page_texts.append(page.get_text("text") or "")
        if i == 0:
            first_spans = _page_lines(page)
        try:
            finder = page.find_tables()
            for t_idx, table in enumerate(finder.tables if finder else []):
                data = table.extract() or []
                if data and len(data) >= 2:
                    tables.append({"page": i + 1, "rows": data, "index": t_idx})
        except Exception:
            pass

    doc.close()
    raw = "\n".join(page_texts)
    paper.raw_text = raw
    lines = _clean_lines(raw)

    paper.doi = _first_match(DOI_RE, raw) or ""
    paper.doi = paper.doi.rstrip(".;,)")
    issns = ISSN_RE.findall(raw)
    if len(issns) >= 1:
        paper.issn_print = issns[0].upper()
    if len(issns) >= 2:
        paper.issn_online = issns[1].upper()

    journal = _detect_journal(raw, first_spans)
    if journal:
        paper.journal_title = journal

    paper.title = _detect_title(first_spans, lines)
    paper.authors, paper.affiliations = _detect_authors_and_affs(lines, raw, paper.title)
    paper.abstract, paper.keywords = _detect_abstract_keywords(lines)
    paper.history = _detect_history(raw)
    ms = MS_ID_RE.search(raw)
    if ms:
        paper.manuscript_id = ms.group(1)

    emails = EMAIL_RE.findall(raw)
    _attach_emails(paper.authors, emails)
    orcids = ORCID_RE.findall(raw)
    for idx, orcid in enumerate(orcids):
        if idx < len(paper.authors):
            paper.authors[idx].orcid = orcid

    body_lines, ref_lines, ack = _split_body_refs(lines)
    paper.acknowledgement = ack
    paper.sections = _parse_sections(body_lines)
    paper.references = _parse_references(ref_lines)
    _attach_tables(paper.sections, tables)
    paper.fig_count = len(re.findall(r"\bFig(?:ure)?\.\s*\d+", raw, re.I))
    paper.table_count = len(tables) or len(re.findall(r"\bTABLE\s+[IVX\d]+", raw, re.I))
    paper.ref_count = len(paper.references)

    if not paper.sections:
        paras = _paragraphs_from_lines(body_lines or lines)
        paper.sections = [
            PaperSection(id="sec1", label="I.", title="Article Body", paragraphs=paras[:40])
        ]

    if not paper.authors:
        paper.authors = [Author(given="Unknown", surname="Author")]
        paper.affiliations = [Affiliation(id="aff1", institution="", raw="")]

    return paper


def _page_lines(page) -> list[dict]:
    out: list[dict] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s.get("text", "") for s in spans).strip()
            if not text:
                continue
            size = max((s.get("size", 0) for s in spans), default=0)
            out.append({"text": text, "size": size, "y": line["bbox"][1]})
    out.sort(key=lambda x: (round(x["y"], 1), -x["size"]))
    return out


def _clean_lines(raw: str) -> list[str]:
    lines = []
    for line in raw.splitlines():
        text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", line)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if HEADER_NOISE.search(text):
            continue
        if re.fullmatch(r"[\d\s\-–]+", text):
            continue
        lines.append(text)
    return lines


def _detect_journal(raw: str, spans: list[dict]) -> str:
    for s in spans[:8]:
        t = s["text"]
        if re.search(r"IEEE\s+.+(Journal|Letters|Magazine|Transactions|Review)", t, re.I):
            return re.sub(r"\s+", " ", t)
        if t.upper().startswith("IEEE ") and len(t) < 80:
            return t
    m = re.search(r"(IEEE\s+[A-Za-z][A-Za-z0-9 &/-]*?(?:Journal|Transactions|Letters|Magazine))", raw)
    return m.group(1) if m else ""


def _detect_title(spans: list[dict], lines: list[str]) -> str:
    usable = [
        s
        for s in spans
        if s["size"] >= 11
        and not HEADER_NOISE.search(s["text"])
        and not re.search(r"IEEE SENSORS|VOL\.|NO\.", s["text"], re.I)
        and len(s["text"]) > 8
    ]
    if usable:
        max_size = max(s["size"] for s in usable)
        title_parts = [s["text"] for s in usable if s["size"] >= max_size - 0.6]
        title = " ".join(title_parts)
        title = re.sub(r"\s+", " ", title).strip()
        if 12 < len(title) < 300:
            return title

    for i, line in enumerate(lines[:20]):
        if ABSTRACT_RE.match(line):
            break
        if len(line) > 25 and not EMAIL_RE.search(line) and "University" not in line:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt and len(nxt) > 20 and not _looks_like_author_line(nxt):
                return f"{line} {nxt}".strip()
            return line
    return "Untitled Article"


def _looks_like_author_line(text: str) -> bool:
    if EMAIL_RE.search(text):
        return True
    if re.search(r"\b(Member|Fellow|Senior Member), IEEE\b", text, re.I):
        return True
    commas = text.count(",")
    return commas >= 1 and len(text) < 220 and not text.endswith(".")


def _detect_authors_and_affs(
    lines: list[str], raw: str, title: str
) -> tuple[list[Author], list[Affiliation]]:
    start = 0
    for i, line in enumerate(lines[:25]):
        if title and title[:40].lower() in line.lower():
            start = i + 1
            break

    author_blob = []
    aff_lines = []
    i = start
    while i < min(len(lines), start + 30):
        line = lines[i]
        if ABSTRACT_RE.match(line) or INDEX_RE.match(line):
            break
        if re.search(
            r"\b(University|Institute|Department|College|Laboratory|Lab\.|India|USA|China|Germany)\b",
            line,
            re.I,
        ) or re.search(r"^\d+\s", line):
            aff_lines.append(line)
        elif _looks_like_author_line(line) or (
            not aff_lines and i < start + 8 and not line.endswith(".")
        ):
            author_blob.append(line)
        i += 1

    authors = _parse_author_names(" ".join(author_blob))
    affiliations = _parse_affiliations(aff_lines)
    if not affiliations:
        affiliations = [Affiliation(id="aff1", raw="; ".join(aff_lines))]

    # corresponding from "Corresponding author"
    corr = re.search(r"Corresponding author[:\s]+([A-Za-z .'-]+)", raw, re.I)
    if corr and authors:
        name = corr.group(1).strip().lower()
        for a in authors:
            full = f"{a.given} {a.surname}".strip().lower()
            if a.surname.lower() in name or full in name:
                a.corresp = True
                break
        else:
            authors[-1].corresp = True
    elif authors:
        authors[-1].corresp = True

    if authors:
        authors[0].aff_ids = ["aff1"]
        if len(affiliations) > 1:
            for idx, a in enumerate(authors):
                a.aff_ids = [affiliations[min(idx, len(affiliations) - 1)].id]

    return authors, affiliations


def _parse_author_names(blob: str) -> list[Author]:
    blob = re.sub(r"\(.*?IEEE.*?\)", "", blob, flags=re.I)
    blob = re.sub(r"[∗*†‡§¶#\d]+", " ", blob)
    blob = blob.replace(" and ", ", ")
    parts = [p.strip(" ,;") for p in blob.split(",") if p.strip(" ,;")]
    authors: list[Author] = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        if len(part) < 4 or EMAIL_RE.search(part):
            continue
        if re.search(r"University|Department|Institute", part, re.I):
            continue
        tokens = part.split()
        if len(tokens) == 1:
            authors.append(Author(given="", surname=tokens[0]))
        else:
            authors.append(Author(given=" ".join(tokens[:-1]), surname=tokens[-1]))
    return authors[:20]


def _parse_affiliations(lines: list[str]) -> list[Affiliation]:
    grouped: list[str] = []
    buf = ""
    for line in lines:
        if re.match(r"^\d+\s", line) and buf:
            grouped.append(buf.strip())
            buf = re.sub(r"^\d+\s+", "", line)
        else:
            buf = f"{buf} {line}".strip()
    if buf:
        grouped.append(re.sub(r"^\d+\s+", "", buf).strip())

    affs: list[Affiliation] = []
    for i, raw in enumerate(grouped[:8], start=1):
        dept = ""
        inst = ""
        city = ""
        country = ""
        post = ""
        dm = re.search(r"(Department of [^,;]+)", raw, re.I)
        if dm:
            dept = dm.group(1).strip()
        im = re.search(r"(University[^,;]*|Institute[^,;]*|College[^,;]*)", raw, re.I)
        if im:
            inst = im.group(1).strip()
        cm = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*,\s*([A-Z][a-z]+)\b", raw)
        if cm:
            city = cm.group(1)
            country = cm.group(2)
        pm = re.search(r"\b(\d{5,6})\b", raw)
        if pm:
            post = pm.group(1)
        affs.append(
            Affiliation(
                id=f"aff{i}",
                department=dept,
                institution=inst or raw[:120],
                city=city,
                post_code=post,
                country=country,
                raw=raw,
            )
        )
    return affs


def _attach_emails(authors: list[Author], emails: list[str]) -> None:
    seen = []
    for e in emails:
        if e.lower() not in seen:
            seen.append(e.lower())
    for i, author in enumerate(authors):
        if i < len(seen):
            author.email = emails[i] if i < len(emails) else seen[i]


def _detect_abstract_keywords(lines: list[str]) -> tuple[str, list[str]]:
    abstract_parts: list[str] = []
    keywords: list[str] = []
    mode = None
    for line in lines:
        am = ABSTRACT_RE.match(line)
        km = INDEX_RE.match(line)
        if am:
            mode = "abstract"
            rest = am.group(1).strip()
            if rest:
                abstract_parts.append(rest)
            continue
        if km:
            mode = "kw"
            rest = km.group(1).strip()
            if rest:
                keywords.extend(_split_kw(rest))
            continue
        if mode == "abstract":
            if MAJOR_SEC_RE.match(line) or line.upper() in {"I. INTRODUCTION", "1. INTRODUCTION"}:
                mode = None
                continue
            abstract_parts.append(line)
        elif mode == "kw":
            if MAJOR_SEC_RE.match(line) or line.startswith("I."):
                mode = None
                continue
            keywords.extend(_split_kw(line))
    abstract = " ".join(abstract_parts).strip()
    abstract = re.sub(r"\s+", " ", abstract)
    kws = [k.strip(" .;") for k in keywords if 2 < len(k.strip()) < 80][:12]
    return abstract, kws


def _split_kw(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;•·]|,(?![^()]*\))", text) if p.strip()]


def _detect_history(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind, value in DATE_RE.findall(raw):
        key = kind.lower()
        if key == "revised" and "revised" in out:
            key = "reviseddate1"
        out[key] = value
    return out


def _split_body_refs(lines: list[str]) -> tuple[list[str], list[str], str]:
    body: list[str] = []
    refs: list[str] = []
    ack_parts: list[str] = []
    mode = "pre"
    for line in lines:
        if ABSTRACT_RE.match(line) or INDEX_RE.match(line):
            mode = "skip_front"
            continue
        if mode == "skip_front":
            if MAJOR_SEC_RE.match(line) or re.match(r"^I\.\s+INTRODUCTION", line, re.I):
                mode = "body"
                body.append(line)
            continue
        if REF_START_RE.match(line):
            mode = "refs"
            continue
        if re.match(r"^(Acknowledgment|Acknowledgement|ACKNOWLEDGMENT)s?\b", line, re.I):
            mode = "ack"
            rest = re.sub(r"^(Acknowledgment|Acknowledgement|ACKNOWLEDGMENT)s?\s*", "", line, flags=re.I)
            if rest:
                ack_parts.append(rest)
            continue
        if mode == "body":
            body.append(line)
        elif mode == "refs":
            if re.match(r"^(Biography|Bios|AUTHORS)\b", line, re.I):
                mode = "done"
                continue
            refs.append(line)
        elif mode == "ack":
            if REF_START_RE.match(line):
                mode = "refs"
            else:
                ack_parts.append(line)
        elif mode == "pre" and MAJOR_SEC_RE.match(line):
            mode = "body"
            body.append(line)
    if mode == "pre":
        # no numbered intro found — treat remaining after keywords as body
        started = False
        for line in lines:
            if INDEX_RE.match(line):
                started = True
                continue
            if started:
                if REF_START_RE.match(line):
                    break
                body.append(line)
    return body, refs, " ".join(ack_parts).strip()


def _parse_sections(lines: list[str]) -> list[PaperSection]:
    sections: list[PaperSection] = []
    current: PaperSection | None = None
    sub: PaperSection | None = None
    buf: list[str] = []
    sec_n = 0

    def flush_buf():
        nonlocal buf
        target = sub or current
        if target and buf:
            para = " ".join(buf).strip()
            if para:
                target.paragraphs.append(para)
        buf = []

    for line in lines:
        fig = FIG_RE.match(line)
        if fig and current:
            flush_buf()
            (sub or current).figures.append(
                {"label": f"Fig. {fig.group(1)}.", "caption": fig.group(2).strip()}
            )
            continue
        tbl = TABLE_RE.match(line)
        if tbl and current:
            flush_buf()
            (sub or current).tables.append(
                {"label": f"TABLE {tbl.group(1)}", "caption": tbl.group(2).strip(), "rows": []}
            )
            continue

        major = MAJOR_SEC_RE.match(line)
        if major:
            flush_buf()
            sec_n += 1
            current = PaperSection(
                id=f"sec{sec_n}",
                label=f"{major.group(1)}.",
                title=_title_case(major.group(2)),
            )
            sections.append(current)
            sub = None
            continue

        subm = SUB_SEC_RE.match(line)
        if subm and current:
            flush_buf()
            sub = PaperSection(
                id=f"{current.id}{subm.group(1).lower()}",
                label=f"{subm.group(1)}.",
                title=subm.group(2).strip(),
            )
            current.children.append(sub)
            continue

        subsub = SUBSUB_SEC_RE.match(line)
        if subsub and (sub or current):
            flush_buf()
            parent = sub or current
            child = PaperSection(
                id=f"{parent.id}{subsub.group(1)}",
                label=f"{subsub.group(1)})",
                title=subsub.group(2).strip(),
            )
            parent.children.append(child)
            sub = child
            continue

        buf.append(line)

    flush_buf()
    return sections


def _title_case(text: str) -> str:
    if text.isupper() and len(text) > 3:
        small = {"AND", "OR", "OF", "THE", "IN", "ON", "FOR", "TO", "A", "AN"}
        parts = text.split()
        out = []
        for i, w in enumerate(parts):
            if i > 0 and w.upper() in small:
                out.append(w.lower())
            else:
                out.append(w[:1].upper() + w[1:].lower())
        return " ".join(out)
    return text.strip()


def _parse_references(lines: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    current = ""
    label = ""
    n = 0
    for line in lines:
        m = re.match(r"^\[(\d+)\]\s*(.*)$", line)
        if m:
            if current:
                n += 1
                items.append({"id": f"ref{n}", "label": label or f"[{n}]", "text": current.strip()})
            label = f"[{m.group(1)}]"
            current = m.group(2)
        else:
            current = f"{current} {line}".strip()
    if current:
        n += 1
        items.append({"id": f"ref{n}", "label": label or f"[{n}]", "text": current.strip()})
    return items


def _attach_tables(sections: list[PaperSection], tables: list[dict[str, Any]]) -> None:
    if not sections or not tables:
        return
    # Place extracted grid tables onto first section that already has a table caption,
    # otherwise append to first results-like section.
    leftover = list(tables)
    for sec in _walk_sections(sections):
        for t in sec.tables:
            if leftover and not t.get("rows"):
                t["rows"] = leftover.pop(0)["rows"]
    if leftover:
        target = sections[-1]
        for extra in leftover:
            target.tables.append(
                {
                    "label": f"TABLE {len(target.tables) + 1}",
                    "caption": "Extracted table",
                    "rows": extra["rows"],
                }
            )


def _walk_sections(sections: list[PaperSection]):
    for s in sections:
        yield s
        yield from _walk_sections(s.children)


def _paragraphs_from_lines(lines: list[str]) -> list[str]:
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        if len(line) < 70 and buf:
            buf.append(line)
            paras.append(" ".join(buf))
            buf = []
        else:
            buf.append(line)
    if buf:
        paras.append(" ".join(buf))
    return [p for p in paras if len(p) > 40][:80]


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(0) if m else None
