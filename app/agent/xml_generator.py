"""Stage 4: generate output XML from template + mappings."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from lxml import etree

from app.llm.client import LLMClient
from app.models.mapping_plan import MappingEntry, MappingPlan
from app.models.paper import Author, PaperData, Section
from app.utils.xml_helpers import (
    apply_ieee_entities_to_tree,
    encode_ieee_text_entities,
    escape_xml_text,
    is_element_node,
    post_process_ieee_entities,
    serialize_tree,
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
            text = encode_ieee_text_entities(raw)
        if text and nodes:
            nodes[0].text = text

    title_nodes = _find_by_local_tag(root, "article-title")
    if title_nodes and paper.title:
        title_nodes[0].text = encode_ieee_text_entities(paper.title)
    abs_nodes = _find_by_local_tag(root, "abstract")
    if abs_nodes and paper.abstract:
        enc = encode_ieee_text_entities(paper.abstract)
        p_nodes = _find_by_local_tag(abs_nodes[0], "p")
        if p_nodes:
            p_nodes[0].text = enc
        else:
            abs_nodes[0].text = enc


def _contrib_rids_referenced(root: etree._Element) -> list[str]:
    xml = etree.tostring(root, encoding="unicode")
    rids = sorted(
        set(re.findall(r'rid="(contrib\d+)"', xml)),
        key=lambda r: int(re.sub(r"^contrib", "", r) or "0"),
    )
    return rids


def _fill_authors(root: etree._Element, authors: list[Author]) -> None:
    contrib_group = _find_by_local_tag(root, "contrib-group")
    if not contrib_group:
        return
    group = contrib_group[0]
    template_contribs = _find_by_local_tag(group, "contrib")
    if not template_contribs:
        return
    proto = template_contribs[0]
    for c in list(group):
        if is_element_node(c) and xml_local_name(c) == "contrib":
            group.remove(c)

    author_list = authors or []
    count = max(len(author_list), len(_contrib_rids_referenced(root)), 1)

    for idx in range(1, count + 1):
        clone = etree.fromstring(etree.tostring(proto))
        clone.set("id", f"contrib{idx}")
        if idx <= len(author_list):
            author = author_list[idx - 1]
            name_nodes = _find_by_local_tag(clone, "string-name")
            if name_nodes:
                name_nodes[0].text = encode_ieee_text_entities(
                author.full_name or f"{author.first_name} {author.last_name}".strip()
            )
            if author.corresponding:
                clone.set("corresp", "yes")
            elif clone.get("corresp") == "yes" and idx > 1:
                clone.set("corresp", "no")
            if idx == 1 and clone.get("primary") is not None:
                clone.set("primary", "yes")
            elif idx > 1 and clone.get("primary") is not None:
                clone.set("primary", "no")
        group.append(clone)


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
        doctype_m = re.search(r"<!DOCTYPE[^>]+>", template_xml, re.DOTALL | re.IGNORECASE)
        doctype = doctype_m.group(0) if doctype_m else None

        parser = etree.XMLParser(remove_blank_text=False, recover=True)
        try:
            root = etree.fromstring(template_xml.encode("utf-8"), parser=parser)
            tree = etree.ElementTree(root)
            _apply_simple_mappings(root, paper, plan)
            if any(m.transform == "loop" and "author" in m.pdf_field for m in plan.mappings):
                _fill_authors(root, paper.authors)
            elif paper.authors:
                _fill_authors(root, paper.authors)
            apply_ieee_entities_to_tree(root)
            output = post_process_ieee_entities(serialize_tree(tree, doctype=doctype))
            etree.fromstring(output.encode("utf-8"))
            return output
        except etree.XMLSyntaxError:
            pass

        prior_block = ""
        if prior_errors:
            prior_block = _render(
                _load_prompt("self_heal.txt"),
                errors="\n".join(prior_errors),
            )

        prompt = _render(
            _load_prompt("xml_generator.txt"),
            template=template_xml[:60000],
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
            return text
        except etree.XMLSyntaxError:
            return template_xml
