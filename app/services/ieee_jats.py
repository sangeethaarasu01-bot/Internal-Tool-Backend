"""Build IEEE JATS 2.0 article XML matching vendor IEEE XML structure."""

from __future__ import annotations

import os
import re
from datetime import datetime
from xml.sax.saxutils import escape

from lxml import etree

from app.services.pdf_extractor import Author, ExtractedPaper, PaperSection

NSMAP = {
    "ali": "http://www.niso.org/schemas/ali/1.0/",
    "xlink": "http://www.w3.org/1999/xlink",
    "mml": "http://www.w3.org/1998/Math/MathML",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# XML 1.0 forbids NULL and most C0 controls (tab/LF/CR are allowed).
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\uFFFE\uFFFF]")


def xml_safe(value: str | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.replace("\x00", "")
    cleaned = _ILLEGAL_XML_CHARS.sub("", cleaned)
    return cleaned.encode("utf-8", "ignore").decode("utf-8")


def generate_ieee_jats(paper: ExtractedPaper) -> str:
    article = etree.Element("article", nsmap=NSMAP)
    article.set("article-type", "research")
    article.set("content-type", "orig-research")
    article.set("dtd-version", "2.0")
    article.set("lifecycle", "final")
    article.set("open-access", "no")
    article.set("peer-reviewed", "yes")
    article.set(XML_LANG, "eng")

    today = datetime.now().strftime("%d/%m/%Y")
    comments = [
        f" Article Processing Date: {today} ",
        " Vendor Name: DCL ",
        " IEEE XML JATS Tagging Guidelines version: v20241024 ",
        " IEEE Math Coding Requirements and Guidelines for Vendors version: v2.4 ",
        " generated_by_ieee_xml_converter ",
    ]
    for c in comments:
        article.append(etree.Comment(c))

    front = etree.SubElement(article, "front")
    _journal_meta(front, paper)
    _article_meta(front, paper)

    body = etree.SubElement(article, "body")
    for section in paper.sections:
        _write_section(body, section)

    back = etree.SubElement(article, "back")
    if paper.acknowledgement:
        ack = etree.SubElement(back, "ack")
        _el(ack, "title", "Acknowledgment")
        _p(ack, paper.acknowledgement)

    ref_list = etree.SubElement(back, "ref-list")
    _el(ref_list, "title", " References ")
    for ref in paper.references:
        _write_ref(ref_list, ref)

    if paper.authors:
        bio_group = etree.SubElement(back, "bio-group")
        for i, author in enumerate(paper.authors, start=1):
            bio = etree.SubElement(bio_group, "bio", id=f"bio{i}")
            p = etree.SubElement(bio, "p")
            xref = etree.SubElement(p, "xref", {"ref-type": "contrib", "rid": f"contrib{i}"})
            xref.text = xml_safe(f"{author.given} {author.surname}".strip())
            xref.tail = " is an author of this article."

    xml_bytes = etree.tostring(
        article,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )
    return xml_bytes.decode("utf-8")


def _journal_meta(front, paper: ExtractedPaper) -> None:
    jm = etree.SubElement(front, "journal-meta")
    _el(jm, "journal-id", paper.journal_id or "0055400", {"journal-id-type": "ieee"})
    acronym = paper.journal_acronym or _acronym(paper.journal_title)
    _el(jm, "journal-id", acronym, {"journal-id-type": "acronym"})
    _el(jm, "journal-id", "ISJEAZ", {"journal-id-type": "coden"})
    tg = etree.SubElement(jm, "journal-title-group")
    _el(tg, "journal-title", paper.journal_title or "IEEE Sensors Journal")
    _el(jm, "issn", paper.issn_print or "1530-437X", {"publication-format": "print"})
    _el(jm, "issn", paper.issn_online or "1558-1748", {"publication-format": "online"})
    pub = etree.SubElement(jm, "publisher")
    _el(pub, "publisher-name", paper.publisher or "IEEE")


def _article_meta(front, paper: ExtractedPaper) -> None:
    am = etree.SubElement(front, "article-meta")
    if paper.doi:
        _el(am, "article-id", paper.doi, {"pub-id-type": "doi"})
    if paper.manuscript_id:
        _el(am, "article-id", paper.manuscript_id, {"pub-id-type": "manuscript"})
    etree.SubElement(am, "xplore-article-id")
    etree.SubElement(am, "xplore-issue")
    etree.SubElement(am, "xplore-pub-id")

    cats = etree.SubElement(am, "article-categories")
    etree.SubElement(cats, "assembly-group", sequence="0")

    tg = etree.SubElement(am, "title-group")
    _el(tg, "article-title", paper.title)

    cg = etree.SubElement(am, "contrib-group")
    for i, author in enumerate(paper.authors, start=1):
        _write_contrib(cg, author, i, primary=(i == 1))

    corr = next((a for a in paper.authors if a.corresp), paper.authors[-1] if paper.authors else None)
    if corr:
        comment = etree.SubElement(cg, "author-comment")
        p = etree.SubElement(comment, "p")
        p.text = "The associate editor coordinating the review of this article and approving it for publication is to be assigned. "
        italic = etree.SubElement(p, "italic")
        italic.text = xml_safe(f"(Corresponding author: {corr.given} {corr.surname}.)".strip())

    for aff in paper.affiliations:
        _write_aff(am, aff)

    year = str(datetime.now().year)
    pub_date = etree.SubElement(
        am,
        "pub-date",
        {
            "date-type": "cover",
            "iso-8601-date": year,
            "pub-type": "print",
            "publication-format": "pdf",
        },
    )
    _el(pub_date, "year", year)
    etree.SubElement(am, "volume")
    etree.SubElement(am, "issue")
    _el(am, "issue-part", "0")
    _el(am, "fpage", "0")
    _el(am, "lpage", str(max(paper.page_count - 1, 1)))

    if paper.history:
        hist = etree.SubElement(am, "history")
        mapping = {
            "received": "receiveddate",
            "revised": "reviseddate1",
            "reviseddate1": "reviseddate1",
            "accepted": "accepteddate",
        }
        for key, value in paper.history.items():
            dtype = mapping.get(key, key)
            iso = _to_iso(value)
            date_el = etree.SubElement(hist, "date", {"date-type": dtype})
            if iso:
                date_el.set("iso-8601-date", iso)
                parts = iso.split("-")
                if len(parts) == 3:
                    _el(date_el, "day", parts[2])
                    _el(date_el, "month", parts[1])
                    _el(date_el, "year", parts[0])
            else:
                _el(date_el, "string-date", value)

    stem = _xml_stem(paper)
    _el(am, "self-uri", f"{stem}.xml", {"content-type": "xml"})
    _el(am, "self-uri", f"{stem}.pdf", {"content-type": "print"})
    _el(am, "self-uri", f"{stem}-x.pdf", {"content-type": "online"})

    if paper.abstract:
        abstract = etree.SubElement(am, "abstract")
        _p_with_math(abstract, paper.abstract)

    if paper.keywords:
        kg = etree.SubElement(am, "kwd-group", {"kwd-group-type": "AuthorFree"})
        for kw in paper.keywords:
            _el(kg, "kwd", kw)

    counts = etree.SubElement(am, "counts")
    etree.SubElement(counts, "fig-count", count=str(paper.fig_count))
    etree.SubElement(counts, "table-count", count=str(paper.table_count))
    etree.SubElement(counts, "equation-count", count="0")
    etree.SubElement(counts, "ref-count", count=str(paper.ref_count))
    etree.SubElement(counts, "page-count", count=str(paper.page_count or 1))


def _write_contrib(parent, author: Author, index: int, primary: bool) -> None:
    attrs = {
        "id": f"contrib{index}",
        "primary": "yes" if primary else "no",
        "corresp": "yes" if author.corresp else "no",
        "contrib-type": "author",
    }
    if author.ieee_member:
        attrs["ieee-member-type"] = author.ieee_member
    contrib = etree.SubElement(parent, "contrib", attrs)
    if author.orcid:
        _el(contrib, "contrib-id", author.orcid, {"contrib-id-type": "orcid"})
    alts = etree.SubElement(contrib, "name-alternatives")
    for use in ("display", "index"):
        sn = etree.SubElement(alts, "string-name", {"specific-use": use})
        if author.given:
            _el(sn, "given-names", f" {author.given} ")
        _el(sn, "surname", f" {author.surname} ")
    if author.email:
        _el(contrib, "email", author.email)
    for aff_id in author.aff_ids or ["aff1"]:
        etree.SubElement(contrib, "xref", {"ref-type": "aff", "rid": aff_id})
    etree.SubElement(contrib, "xref", {"ref-type": "bio", "rid": f"bio{index}"})


def _write_aff(parent, aff) -> None:
    node = etree.SubElement(parent, "aff", id=aff.id)
    wrap = etree.SubElement(node, "institution-wrap")
    if aff.department:
        _el(wrap, "institution", aff.department, {"content-type": "department"})
    if aff.institution:
        _el(wrap, "institution", aff.institution, {"content-type": "institution"})
    elif aff.raw:
        _el(wrap, "institution", aff.raw, {"content-type": "institution"})
    if aff.city:
        _el(node, "city", aff.city)
    if aff.post_code:
        _el(node, "post-code", aff.post_code)
    if aff.country:
        _el(node, "country", aff.country)


def _write_section(parent, section: PaperSection) -> None:
    sec = etree.SubElement(parent, "sec", id=section.id)
    if section.label:
        _el(sec, "label", section.label)
    if section.title:
        _el(sec, "title", section.title)
    for para in section.paragraphs:
        _p_with_math(sec, para)
        # inline table/fig may follow in source; attach after first para block
    for fig in section.figures:
        _write_fig(sec, fig)
    for table in section.tables:
        _write_table(sec, table)
    for child in section.children:
        _write_section(sec, child)


def _write_fig(parent, fig: dict) -> None:
    fig_id = "fig" + re.sub(r"\D+", "", fig.get("label", "1") or "1") or "fig1"
    node = etree.SubElement(parent, "fig", id=fig_id)
    _el(node, "label", fig.get("label", "Fig. 1."))
    cap = etree.SubElement(node, "caption")
    _p(cap, fig.get("caption") or "")
    etree.SubElement(
        node,
        "graphic",
        {f"{{{NSMAP['xlink']}}}href": f"{fig_id}.eps"},
    )


def _write_table(parent, table: dict) -> None:
    tid = "table" + re.sub(r"\W+", "", table.get("label", "1")).lower()
    wrap = etree.SubElement(parent, "table-wrap", id=tid or "table1")
    _el(wrap, "label", table.get("label", "TABLE I"))
    cap = etree.SubElement(wrap, "caption")
    title = etree.SubElement(cap, "title")
    title.text = xml_safe(table.get("caption") or "Table")
    rows = table.get("rows") or []
    if rows:
        cols = max(len(r) for r in rows)
        tbl = etree.SubElement(
            wrap,
            "table",
            {"rules": "all", "frame": "box", "cellpadding": "5"},
        )
        colgroup = etree.SubElement(tbl, "colgroup")
        etree.SubElement(colgroup, "col", span=str(cols))
        thead = etree.SubElement(tbl, "thead")
        _table_row(thead, rows[0], header=True, cols=cols)
        tbody = etree.SubElement(tbl, "tbody")
        for row in rows[1:]:
            _table_row(tbody, row, header=False, cols=cols)


def _table_row(parent, row, header: bool, cols: int) -> None:
    tr = etree.SubElement(parent, "tr")
    tag = "th" if header else "td"
    padded = list(row) + [""] * (cols - len(row))
    for cell in padded[:cols]:
        cell_el = etree.SubElement(tr, tag)
        cell_el.text = xml_safe((cell or "").strip())


def _write_ref(parent, ref: dict) -> None:
    node = etree.SubElement(parent, "ref", id=ref["id"])
    _el(node, "label", f" {ref['label']} " if not str(ref["label"]).startswith(" ") else ref["label"])
    citation = etree.SubElement(
        node,
        "mixed-citation",
        {"publication-type": "periodical", "publication-format": "print"},
    )
    text = xml_safe(ref.get("text") or "")
    title_m = re.search(r"[“\"](.+?)[”\"]", text)
    doi_m = re.search(r"10\.\d{4,9}/\S+", text)
    year_m = re.search(r"\b(19|20)\d{2}\b", text)
    source_m = re.search(r"(IEEE[^,.]+|Sens\. Actuators[^,.]*|Electroanalysis|Planta Medica)", text)

    authors_part = text.split("“")[0] if "“" in text or '"' in text else text.split(".")[0]
    names = _citation_names(authors_part)
    if names:
        pg = etree.SubElement(citation, "person-group", {"person-group-type": "author"})
        trimmed = names[:8]
        for i, (given, surname) in enumerate(trimmed):
            sn = etree.SubElement(pg, "string-name")
            if given:
                _el(sn, "given-names", f" {given} ")
            _el(sn, "surname", f" {surname} ")
            if i < len(trimmed) - 1:
                sn.tail = ", "
        if "et al" in authors_part.lower():
            etree.SubElement(pg, "etal")

    if title_m:
        if len(citation):
            citation[-1].tail = ", “"
        _el(citation, "article-title", f" {title_m.group(1)} ")
        citation[-1].tail = ", "

    if source_m:
        src = etree.SubElement(citation, "source")
        if "IEEE" in source_m.group(1):
            src.set("specific-use", "IEEE")
        src.text = xml_safe(f" {source_m.group(1)} ")
        src.tail = ", "

    vol = re.search(r"vol\.\s*(\d+)", text, re.I)
    iss = re.search(r"no\.\s*(\d+)", text, re.I)
    pages = re.search(r"pp\.\s*(\d+)\s*[–-]\s*(\d+)", text, re.I)
    if vol:
        _el(citation, "volume", f" {vol.group(1)} ")
        citation[-1].tail = ", "
    if iss:
        _el(citation, "issue", f" {iss.group(1)} ")
        citation[-1].tail = ", "
    if pages:
        _el(citation, "fpage", f" {pages.group(1)} ")
        citation[-1].tail = "–"
        _el(citation, "lpage", f" {pages.group(2)} ")
        citation[-1].tail = ", "
    if year_m:
        _el(citation, "year", f" {year_m.group(0)} ")
        citation[-1].tail = ". "
    if doi_m:
        if len(citation):
            citation[-1].tail = (citation[-1].tail or "") + "doi: "
        _el(citation, "object-id", doi_m.group(0).rstrip("."), {"pub-id-type": "doi"})
        citation[-1].tail = ". "

    if not list(citation):
        citation.text = xml_safe(text)


def _citation_names(blob: str) -> list[tuple[str, str]]:
    blob = blob.replace(" and ", ", ")
    parts = [p.strip(" ,.") for p in blob.split(",") if p.strip(" ,.")]
    names = []
    for part in parts:
        if "et al" in part.lower():
            continue
        tokens = part.replace(".", "").split()
        if not tokens:
            continue
        if len(tokens) == 1:
            names.append(("", tokens[0]))
        else:
            names.append((" ".join(tokens[:-1]), tokens[-1]))
    return names[:12]


def _p(parent, text: str):
    p = etree.SubElement(parent, "p")
    p.text = xml_safe(text)
    return p


def _p_with_math(parent, text: str):
    """Turn simple LaTeX-like snippets into IEEE inline-formula/tex-math."""
    text = xml_safe(text)
    p = etree.SubElement(parent, "p")
    pattern = re.compile(r"(\$[^$]+\$|R\^2|mse|t-SNE)", re.I)
    pos = 0
    last = p
    first = True
    for m in pattern.finditer(text):
        before = xml_safe(text[pos : m.start()])
        token = m.group(0)
        if first:
            p.text = before
            first = False
        else:
            last.tail = xml_safe((last.tail or "") + before)
        if token.startswith("$") and token.endswith("$"):
            last = _inline_tex(p, token[1:-1])
        elif token.lower() == "r^2":
            italic = etree.SubElement(p, "italic")
            italic.text = "R"
            sup = etree.SubElement(p, "sup")
            sup.text = "2"
            last = sup
        else:
            last = _inline_tex(p, token)
        pos = m.end()
    rest = xml_safe(text[pos:])
    if first:
        p.text = text
    else:
        last.tail = xml_safe((last.tail or "") + rest)
    _link_xrefs(p)
    return p


def _inline_tex(parent, tex: str):
    formula = etree.SubElement(parent, "inline-formula")
    tm = etree.SubElement(formula, "tex-math", {"notation": "LaTeX"})
    tm.text = xml_safe(tex)
    return formula


def _link_xrefs(p_el) -> None:
    if p_el.text:
        text = p_el.text
        m = re.search(r"\[(\d+)\]", text)
        if m:
            before, after = text[: m.start()], text[m.end() :]
            p_el.text = xml_safe(before)
            xref = etree.SubElement(p_el, "xref", {"ref-type": "bibr", "rid": f"ref{m.group(1)}"})
            xref.text = xml_safe(m.group(0))
            xref.tail = xml_safe(after)


def _el(parent, tag: str, text: str | None = None, attrs: dict | None = None):
    node = etree.SubElement(parent, tag, attrs or {})
    if text is not None:
        node.text = xml_safe(text)
    return node


def _acronym(title: str) -> str:
    words = re.findall(r"[A-Z][a-z]+|[A-Z]+", title or "")
    if not words:
        return "JSEN"
    letters = "".join(w[0] for w in words if w.lower() not in {"of", "the", "and", "on"})
    return letters[:8].upper() or "JSEN"


def _xml_stem(paper: ExtractedPaper) -> str:
    if paper.doi:
        tail = paper.doi.split("/")[-1]
        return f"jsen-converted-{tail}"
    base = os.path.splitext(os.path.basename(paper.source_filename or "article"))[0]
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-").lower()
    return safe or "ieee-article"


def _to_iso(value: str) -> str:
    value = value.replace(",", "").strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%d %b. %Y", "%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def safe_text(value: str) -> str:
    return escape(value or "")
