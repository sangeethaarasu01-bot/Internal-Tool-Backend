"""Stage 4: generate output XML from template + mappings."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from pathlib import Path

from lxml import etree

from app.llm.client import LLMClient
from app.models.mapping_plan import MappingEntry, MappingPlan
from app.models.paper import Author, PaperData, Section
from app.utils.logger import logger
from app.utils.text_utils import infer_drop_cap_from_paragraph_start
from app.utils.xml_text import normalize_person_name_text
from app.utils.template_skeleton import (
    clear_subtree_text,
    paragraph_has_block_structure,
    prepare_template_for_pdf_content,
    skeleton_template_xml,
)
from app.utils.xml_helpers import (
    apply_ieee_entities_to_tree,
    clean_extracted_abstract,
    escape_xml_text,
    extract_doctype_declaration,
    finalize_ieee_xml,
    is_element_node,
    normalize_doctype_spacing,
    normalize_text_for_xml_dom,
    parse_xml_string,
    reorder_contrib_group_author_comments,
    serialize_tree,
    strip_xml_prolog_for_parse,
    wrap_drop_cap_in_paragraph,
    xml_local_name,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(prompt_template: str, **kwargs: str) -> str:
    out = prompt_template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", v)
    return out


def _get_field(paper: PaperData, field: str) -> object:
    if field == "title":
        return paper.title
    if field == "abstract":
        return paper.abstract
    if field == "authors[]":
        return paper.authors
    if field == "keywords[]":
        return paper.keywords
    if field.startswith("metadata."):
        return paper.metadata.get(field.split(".", 1)[1], "")
    return ""


def _find_by_local_tag(root: etree._Element, tag: str) -> list[etree._Element]:
    return root.xpath(f".//*[local-name()='{tag}']")


def _apply_simple_mappings(
    root: etree._Element,
    paper: PaperData,
    plan: MappingPlan,
) -> None:
    for entry in plan.mappings:
        if entry.transform not in ("none", "escape_xml"):
            continue
        if entry.xml_tag == "abstract":
            continue
        nodes = _find_by_local_tag(root, entry.xml_tag)
        if not nodes:
            continue
        val = _get_field(paper, entry.pdf_field)
        if isinstance(val, list):
            continue
        raw = str(val)
        if entry.transform == "escape_xml":
            text = escape_xml_text(raw)
        else:
            text = normalize_text_for_xml_dom(raw)
        if text and nodes:
            nodes[0].text = text

    title_nodes = _find_by_local_tag(root, "article-title")
    if title_nodes and paper.title:
        title_nodes[0].text = normalize_text_for_xml_dom(paper.title)


def _fill_abstract(root: etree._Element, abstract: str) -> None:
    """Replace template abstract with PDF text (keep <abstract> wrapper from template)."""
    abs_nodes = _find_by_local_tag(root, "abstract")
    if not abs_nodes:
        return
    cleaned = clean_extracted_abstract(abstract) if abstract else ""
    if not cleaned:
        return
    abs_el = abs_nodes[0]
    abs_el.text = None
    for child in list(abs_el):
        if is_element_node(child):
            abs_el.remove(child)
    p_nodes = _find_by_local_tag(abs_el, "p")
    if p_nodes:
        p = p_nodes[0]
        p.clear()
        p.text = normalize_text_for_xml_dom(cleaned)
        return
    p = etree.SubElement(abs_el, "p")
    p.text = normalize_text_for_xml_dom(cleaned)


def _set_text_element(parent: etree._Element, tag: str, text: str) -> None:
    if not text.strip():
        return
    el = etree.SubElement(parent, tag)
    el.text = normalize_text_for_xml_dom(text)


def _append_paper_section(parent: etree._Element, section: Section) -> None:
    sec = etree.SubElement(parent, "sec", id=section.id or "sec1")
    if section.label:
        _set_text_element(sec, "label", section.label)
    if section.title:
        _set_text_element(sec, "title", section.title)
    for para in section.paragraphs:
        if not para.strip():
            continue
        p = etree.SubElement(sec, "p")
        p.text = normalize_text_for_xml_dom(para)
    for sub in section.subsections:
        _append_paper_section(sec, sub)


def _direct_children(parent: etree._Element, local_tag: str) -> list[etree._Element]:
    return [
        c
        for c in parent
        if is_element_node(c) and xml_local_name(c) == local_tag
    ]


def _fill_or_create_child(parent: etree._Element, tag: str, text: str) -> None:
    if not text or not text.strip():
        return
    nodes = _direct_children(parent, tag)
    el = nodes[0] if nodes else etree.SubElement(parent, tag)
    el.text = None
    for child in list(el):
        if is_element_node(child):
            el.remove(child)
    el.text = normalize_text_for_xml_dom(text)


def _set_paragraph_element(p_el: etree._Element, para: str) -> None:
    p_el.text = None
    for child in list(p_el):
        if is_element_node(child):
            p_el.remove(child)
    p_el.text = normalize_text_for_xml_dom(para)


def _paragraph_accepts_pdf_text(p_el: etree._Element) -> bool:
    """Do not overwrite IEEE paragraphs that still carry equations or formal statements."""
    return not paragraph_has_block_structure(p_el)


def _merge_sec_from_paper(template_sec: etree._Element, paper_sec: Section) -> None:
    """Fill cleared template section slots with PDF text; keep fig/table/formula nodes."""
    if paper_sec.label:
        _fill_or_create_child(template_sec, "label", paper_sec.label)
    if paper_sec.title:
        _fill_or_create_child(template_sec, "title", paper_sec.title)

    paras = [p.strip() for p in paper_sec.paragraphs if p.strip()]
    p_slots = [
        p for p in _direct_children(template_sec, "p") if _paragraph_accepts_pdf_text(p)
    ]
    for i, para in enumerate(paras):
        if i < len(p_slots):
            _set_paragraph_element(p_slots[i], para)
        else:
            p = etree.SubElement(template_sec, "p")
            p.text = normalize_text_for_xml_dom(para)

    template_subs = _direct_children(template_sec, "sec")
    paper_subs = paper_sec.subsections
    for i, t_sub in enumerate(template_subs):
        if i < len(paper_subs):
            _merge_sec_from_paper(t_sub, paper_subs[i])
    for j in range(len(template_subs), len(paper_subs)):
        _append_paper_section(template_sec, paper_subs[j])


def _drop_cap_letters_for_section(paper_sec: Section) -> list[str | None]:
    if paper_sec.drop_cap_letters:
        return list(paper_sec.drop_cap_letters)
    return [infer_drop_cap_from_paragraph_start(p) for p in paper_sec.paragraphs]


def _apply_drop_caps_for_section(template_sec: etree._Element, paper_sec: Section) -> None:
    letters = _drop_cap_letters_for_section(paper_sec)
    if not any(letters):
        return
    p_els = _direct_children(template_sec, "p")
    for i, letter in enumerate(letters):
        if not letter or i >= len(p_els):
            continue
        if wrap_drop_cap_in_paragraph(p_els[i], letter):
            logger.debug("Applied drop-cap <bold>{}</bold> in section {}", letter, paper_sec.id)
    template_subs = _direct_children(template_sec, "sec")
    for i, t_sub in enumerate(template_subs):
        if i < len(paper_sec.subsections):
            _apply_drop_caps_for_section(t_sub, paper_sec.subsections[i])


def _apply_drop_caps_from_paper(root: etree._Element, paper: PaperData) -> None:
    bodies = _find_by_local_tag(root, "body")
    if not bodies or not paper.sections:
        return
    top_secs = _direct_children(bodies[0], "sec")
    for i, t_sec in enumerate(top_secs):
        if i < len(paper.sections):
            _apply_drop_caps_for_section(t_sec, paper.sections[i])


def _fill_body_from_paper(root: etree._Element, paper: PaperData) -> None:
    """Merge PDF sections into template body without destroying IEEE structure."""
    bodies = _find_by_local_tag(root, "body")
    if not bodies or not paper.sections:
        return
    body = bodies[0]
    top_secs = _direct_children(body, "sec")
    if not top_secs:
        for section in paper.sections:
            _append_paper_section(body, section)
        return
    for i, t_sec in enumerate(top_secs):
        if i < len(paper.sections):
            _merge_sec_from_paper(t_sec, paper.sections[i])
    for j in range(len(top_secs), len(paper.sections)):
        _append_paper_section(body, paper.sections[j])


def _fill_keywords(root: etree._Element, keywords: list[str]) -> None:
    if not keywords:
        return
    kwd_groups = _find_by_local_tag(root, "kwd-group")
    if not kwd_groups:
        return
    group = kwd_groups[0]
    for child in list(group):
        if is_element_node(child) and xml_local_name(child) == "kwd":
            group.remove(child)
    for token in keywords:
        word = token.strip()
        if not word:
            continue
        kwd = etree.SubElement(group, "kwd")
        kwd.text = normalize_text_for_xml_dom(word)


def _fill_references_from_paper(root: etree._Element, paper: PaperData) -> None:
    if not paper.references:
        return
    backs = _find_by_local_tag(root, "back")
    if not backs:
        return
    back = backs[0]
    ref_lists = _find_by_local_tag(back, "ref-list")
    if not ref_lists:
        return
    ref_list = ref_lists[0]
    for child in list(ref_list):
        if is_element_node(child) and xml_local_name(child) == "ref":
            ref_list.remove(child)
    for ref in paper.references:
        ref_el = etree.SubElement(ref_list, "ref", id=ref.id)
        label = etree.SubElement(ref_el, "label")
        label.text = f"[{ref.number}]"
        mixed = etree.SubElement(ref_el, "mixed-citation")
        p = etree.SubElement(mixed, "p")
        p.text = normalize_text_for_xml_dom(ref.raw_text)


def _contrib_rids_referenced(root: etree._Element) -> list[str]:
    xml = etree.tostring(root, encoding="unicode")
    rids = sorted(
        set(re.findall(r'rid="(contrib\d+)"', xml)),
        key=lambda r: int(re.sub(r"^contrib", "", r) or "0"),
    )
    return rids


def _bio_index(rid: str) -> int:
    m = re.match(r"^bio(\d+)$", rid or "")
    return int(m.group(1)) if m else 0


def _cap_authors_to_template_slots(
    authors: list[Author],
    template_contrib_count: int,
    root: etree._Element,
) -> list[Author]:
    """Prefer template author/bio slots so PDF over-extraction does not inflate contrib count."""
    cap = template_contrib_count
    bio_ids = [
        b.get("id")
        for b in _find_by_local_tag(root, "bio")
        if b.get("id")
    ]
    if bio_ids:
        cap = max(cap, len(bio_ids))
    if cap and len(authors) > cap:
        return authors[:cap]
    return authors


def sync_bio_xrefs(root: etree._Element) -> None:
    """Ensure every contrib bio xref rid has a matching <bio id=\"...\"> (template-adaptive)."""
    bio_rids: set[str] = set()
    for xref in root.xpath(".//*[local-name()='xref']"):
        if xref.get("ref-type") == "bio":
            rid = (xref.get("rid") or "").strip()
            if rid:
                bio_rids.add(rid)
    if not bio_rids:
        return

    bio_group_nodes = _find_by_local_tag(root, "bio-group")
    group: etree._Element | None
    bios: list[etree._Element]
    if bio_group_nodes:
        group = bio_group_nodes[0]
        bios = [
            c
            for c in group
            if is_element_node(c) and xml_local_name(c) == "bio"
        ]
    else:
        bios = _find_by_local_tag(root, "bio")
        group = bios[0].getparent() if bios else None
        if group is None:
            back_nodes = _find_by_local_tag(root, "back")
            if not back_nodes:
                return
            group = etree.SubElement(back_nodes[0], "bio-group")
            bios = []

    existing = {b.get("id") for b in bios if b.get("id")}
    prototype = bios[-1] if bios else None

    for rid in sorted(bio_rids, key=_bio_index):
        if rid in existing:
            continue
        idx = _bio_index(rid) or 1
        if prototype is not None:
            clone = etree.fromstring(etree.tostring(prototype))
        else:
            clone = etree.Element("bio")
            p = etree.SubElement(clone, "p")
            etree.SubElement(
                p,
                "xref",
                {"ref-type": "contrib", "rid": f"contrib{idx}"},
            )
        clone.set("id", rid)
        for inner in clone.xpath(".//*[local-name()='xref']"):
            if inner.get("ref-type") == "contrib":
                inner.set("rid", f"contrib{idx}")
        clear_subtree_text(clone)
        group.append(clone)
        existing.add(rid)


def repair_xml_xrefs(xml: str) -> str:
    """Deterministic xref repair (bio targets) before validation."""
    root = parse_xml_string(xml)
    sync_bio_xrefs(root)
    repaired = etree.tostring(root, encoding="unicode")
    return finalize_ieee_xml(repaired)


def _contrib_children(group: etree._Element) -> list[etree._Element]:
    return [
        c
        for c in group
        if is_element_node(c) and xml_local_name(c) == "contrib"
    ]


def _author_name_parts(author: Author) -> tuple[str, str]:
    first = (author.first_name or "").strip()
    last = (author.last_name or "").strip()
    if first and last:
        return first, last
    full = (author.full_name or "").strip()
    if full:
        tokens = full.split()
        if len(tokens) >= 2:
            return " ".join(tokens[:-1]), tokens[-1]
        return full, ""
    return first, last


def _set_text_on_tag(parent: etree._Element, tag: str, text: str) -> None:
    nodes = _find_by_local_tag(parent, tag)
    if nodes and text:
        nodes[0].text = normalize_text_for_xml_dom(text)


def _clear_contrib_document_text(contrib: etree._Element) -> None:
    """Remove sample author names/email from a contrib shell (keep structure/attrs)."""
    for tag in ("given-names", "surname", "email"):
        for node in _find_by_local_tag(contrib, tag):
            node.text = None
    for string_name in _find_by_local_tag(contrib, "string-name"):
        string_name.text = None
        for child in list(string_name):
            if is_element_node(child):
                string_name.remove(child)


def _fill_affiliations(root: etree._Element, paper: PaperData) -> None:
    aff_nodes = _find_by_local_tag(root, "aff")
    if not aff_nodes:
        return
    if not paper.affiliations:
        for aff in aff_nodes:
            clear_subtree_text(aff)
        return
    for idx, aff_el in enumerate(aff_nodes):
        if idx >= len(paper.affiliations):
            break
        data = paper.affiliations[idx]
        inst_nodes = _find_by_local_tag(aff_el, "institution")
        if inst_nodes and data.institution:
            inst_nodes[0].text = normalize_text_for_xml_dom(data.institution)
        if data.city:
            _set_text_on_tag(aff_el, "city", data.city)
        if data.country:
            _set_text_on_tag(aff_el, "country", data.country)
        if data.department:
            _set_text_on_tag(aff_el, "addr-line", data.department)


def _apply_author_to_contrib(contrib: etree._Element, author: Author, idx: int) -> None:
    given, surname = _author_name_parts(author)
    given_enc = normalize_person_name_text(given) if given else ""
    surname_enc = normalize_person_name_text(surname) if surname else ""

    for string_name in _find_by_local_tag(contrib, "string-name"):
        string_name.text = None
        if given_enc:
            _set_text_on_tag(string_name, "given-names", given_enc)
        if surname_enc:
            _set_text_on_tag(string_name, "surname", surname_enc)

    if author.email:
        _set_text_on_tag(contrib, "email", author.email)

    orcid_nodes = [
        n
        for n in _find_by_local_tag(contrib, "contrib-id")
        if n.get("contrib-id-type") == "orcid"
    ]
    if author.orcid:
        if orcid_nodes:
            orcid_nodes[0].text = normalize_text_for_xml_dom(author.orcid)
    else:
        for node in orcid_nodes:
            if (node.text or "").strip():
                continue
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

    for xref in _find_by_local_tag(contrib, "xref"):
        if xref.get("ref-type") == "bio":
            xref.set("rid", f"bio{idx}")

    contrib.set("id", f"contrib{idx}")
    if author.corresponding:
        contrib.set("corresp", "yes")
    elif contrib.get("corresp") == "yes" and idx > 1:
        contrib.set("corresp", "no")
    if idx == 1 and contrib.get("primary") is not None:
        contrib.set("primary", "yes")
    elif idx > 1 and contrib.get("primary") is not None:
        contrib.set("primary", "no")


def _fill_authors(root: etree._Element, authors: list[Author]) -> None:
    contrib_group = _find_by_local_tag(root, "contrib-group")
    if not contrib_group:
        return
    group = contrib_group[0]
    template_contribs = _contrib_children(group)
    if not template_contribs:
        return
    fallback_proto = template_contribs[0]
    for c in list(template_contribs):
        group.remove(c)

    author_list = _cap_authors_to_template_slots(
        authors or [],
        len(template_contribs),
        root,
    )
    count = max(
        len(author_list),
        len(template_contribs),
        len(_contrib_rids_referenced(root)),
        1,
    )

    for idx in range(1, count + 1):
        if idx <= len(template_contribs):
            clone = etree.fromstring(etree.tostring(template_contribs[idx - 1]))
        else:
            clone = etree.fromstring(etree.tostring(fallback_proto))
        if idx <= len(author_list):
            _apply_author_to_contrib(clone, author_list[idx - 1], idx)
        else:
            clone.set("id", f"contrib{idx}")
            _clear_contrib_document_text(clone)
            for xref in _find_by_local_tag(clone, "xref"):
                if xref.get("ref-type") == "bio":
                    xref.set("rid", f"bio{idx}")
        group.append(clone)
    reorder_contrib_group_author_comments(root)


def _generate_from_template_dom(
    template_xml: str,
    paper: PaperData,
    plan: MappingPlan,
) -> str:
    xml_body, doctype = strip_xml_prolog_for_parse(template_xml)
    if not doctype:
        raw_dt = extract_doctype_declaration(template_xml)
        doctype = normalize_doctype_spacing(raw_dt) if raw_dt else None
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    root = etree.fromstring(xml_body.encode("utf-8"), parser=parser)
    tree = etree.ElementTree(root)
    merge_pdf = prepare_template_for_pdf_content(root, paper)
    logger.debug(
        "XML DOM: merge_pdf={} PDF title={} sections={}",
        merge_pdf,
        (paper.title or "")[:80],
        len(paper.sections),
    )
    if merge_pdf:
        _apply_simple_mappings(root, paper, plan)
        _fill_abstract(root, paper.abstract)
        if any(m.transform == "loop" and "author" in m.pdf_field for m in plan.mappings):
            _fill_authors(root, paper.authors)
        elif paper.authors:
            _fill_authors(root, paper.authors)
        _fill_keywords(root, paper.keywords)
        _fill_affiliations(root, paper)
        _fill_body_from_paper(root, paper)
        _fill_references_from_paper(root, paper)
    else:
        logger.info(
            "PDF extraction unreliable for this file; output keeps template "
            "front/body/back text and structure (IEEE proof + vendor XML workflow)."
        )
    _apply_drop_caps_from_paper(root, paper)
    sync_bio_xrefs(root)
    output = finalize_ieee_xml(serialize_tree(tree, doctype=doctype))
    parse_xml_string(output)
    return output


class XMLGenerator:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def generate(
        self,
        template_xml: str,
        paper: PaperData,
        plan: MappingPlan,
        on_event: Callable[[dict], None] | None = None,
        prior_errors: list[str] | None = None,
    ) -> str:
        try:
            return await asyncio.to_thread(
                _generate_from_template_dom,
                template_xml,
                paper,
                plan,
            )
        except etree.XMLSyntaxError:
            pass

        prior_block = ""
        if prior_errors:
            prior_block = _render(
                _load_prompt("self_heal.txt"),
                errors="\n".join(prior_errors),
            )

        structural_template = skeleton_template_xml(template_xml, paper)
        logger.info(
            "LLM XML fallback: using structural template ({} chars), paper title={!r:.60}",
            len(structural_template),
            paper.title,
        )
        prompt = _render(
            _load_prompt("xml_generator.txt"),
            template=structural_template[:60000],
            paper_data=paper.model_dump_json()[:30000],
            mapping_plan=plan.model_dump_json()[:20000],
            prior_errors_block=prior_block,
        )
        system = _load_prompt("system.txt")
        if on_event:
            on_event({"type": "log", "message": "LLM XML generation"})
        resp = await self.llm.complete(system=system, user=prompt, max_tokens=16000, temperature=0.0)
        text = resp.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:xml)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        try:
            etree.fromstring(text.encode("utf-8"))
            return finalize_ieee_xml(text)
        except etree.XMLSyntaxError:
            logger.error("LLM XML output invalid; using deterministic DOM fill")
            return await asyncio.to_thread(
                _generate_from_template_dom,
                template_xml,
                paper,
                plan,
            )
