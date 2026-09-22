"""Stage 1: analyze XML template into SchemaMap."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from lxml import etree

from app.agent.cache import SchemaCache
from app.llm.client import LLMClient
from app.models.schema_map import SchemaMap, SchemaElement
from app.utils.hashing import sha256_file
from app.utils.xml_helpers import element_to_skeleton, iter_element_children, xml_local_name

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _render(prompt_template: str, **kwargs: str) -> str:
    out = prompt_template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", v)
    return out


def _sibling_cardinality(elem: etree._Element, tag: str) -> str:
    parent = elem.getparent()
    if parent is None:
        return "single"
    count = sum(1 for c in iter_element_children(parent) if xml_local_name(c) == tag)
    return "repeating" if count > 1 else "single"


def _flatten_elements(elements: list[SchemaElement], acc: list[SchemaElement]) -> None:
    for el in elements:
        acc.append(el)
        _flatten_elements(el.children, acc)


def _build_schema_from_tree(tree: etree._ElementTree, template_hash: str) -> SchemaMap:
    """Deterministic fallback when LLM returns minimal schema."""
    root = tree.getroot()
    root_tag = xml_local_name(root)
    namespaces = {k if k else "xmlns": v for k, v in root.nsmap.items() if k is not None or v}
    if None in root.nsmap:
        namespaces["xmlns"] = root.nsmap[None]

    def walk(elem: etree._Element, path: str) -> SchemaElement:
        tag = xml_local_name(elem)
        xpath = f"{path}/{tag}" if path else tag
        text = (elem.text or "").strip()[:200]
        children = [walk(c, xpath) for c in iter_element_children(elem)]
        semantic = "unknown"
        lower = tag.lower()
        if "title" in lower and "article" in lower:
            semantic = "paper_title"
        elif tag == "abstract":
            semantic = "abstract"
        elif "contrib" in lower:
            semantic = "author_name"
        elif "kwd" in lower or "keyword" in lower:
            semantic = "keyword"
        return SchemaElement(
            xpath=xpath,
            tag=tag,
            semantic=semantic,
            cardinality=_sibling_cardinality(elem, tag),
            data_type="string",
            required=False,
            attributes=dict(elem.attrib),
            sample=text,
            children=children,
            notes="",
        )

    top = walk(root, "")
    flat: list[SchemaElement] = []
    _flatten_elements([top], flat)
    return SchemaMap(
        root_tag=root_tag,
        namespaces=namespaces,
        doctype=None,
        elements=flat[:200],
        template_hash=template_hash,
        llm_model="deterministic",
        llm_cost_usd=0.0,
    )


class SchemaAnalyzer:
    def __init__(self, llm: LLMClient, cache: SchemaCache | None = None) -> None:
        self.llm = llm
        self.cache = cache or SchemaCache()

    async def analyze(
        self,
        template_path: Path,
        on_event: Callable[[dict], None] | None = None,
    ) -> SchemaMap:
        def emit(event_type: str, message: str) -> None:
            if on_event:
                on_event({"type": event_type, "message": message})

        h = sha256_file(template_path)
        cached = self.cache.get(h)
        if cached:
            emit("log", "Schema cache hit")
            return cached

        tree = etree.parse(str(template_path))
        raw_xml = template_path.read_text(encoding="utf-8", errors="replace")
        skeleton = element_to_skeleton(tree.getroot())
        system = _load_prompt("system.txt")
        prompt = _render(
            _load_prompt("schema_analyzer.txt"),
            template=raw_xml[:50000],
            skeleton=json.dumps(skeleton, indent=2)[:30000],
        )
        try:
            resp = await self.llm.complete(system=system, user=prompt, json_mode=True, temperature=0.0)
        except Exception as exc:
            emit("log", f"LLM unavailable ({exc}); using template-only schema analysis")
            schema = _build_schema_from_tree(tree, h)
            self.cache.set(h, schema)
            return schema
        if resp.offline_fallback:
            emit(
                "log",
                "Anthropic credits/API unavailable — running offline schema analysis (add credits for full LLM quality)",
            )
        try:
            data = json.loads(resp.text)
            if len(data.get("elements", [])) < 5:
                schema = _build_schema_from_tree(tree, h)
                schema.llm_model = resp.model
                schema.llm_cost_usd = resp.cost_usd
            else:
                schema = SchemaMap(
                    **data,
                    template_hash=h,
                    llm_model=resp.model,
                    llm_cost_usd=resp.cost_usd,
                )
        except (json.JSONDecodeError, TypeError, ValueError):
            schema = _build_schema_from_tree(tree, h)
            schema.llm_model = resp.model
            schema.llm_cost_usd = resp.cost_usd

        self.cache.set(h, schema)
        emit("log", f"Schema analyzed: {len(schema.elements)} elements")
        return schema
