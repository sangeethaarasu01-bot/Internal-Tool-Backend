"""Parse IEEE JATS reference XML templates into machine-readable schema JSON.

Deterministic only — no LLM calls.  The output schema is swappable: point at a
different template XML and regenerate ``template_schema.json`` without code changes.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from lxml import etree

from app.models.template_schema import (
    LlmHints,
    RootAttributeSpec,
    SectionBoundarySpec,
    TagSpec,
    TemplateSchema,
)

XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

DEFAULT_KNOWN_TAGS_PATH = Path(__file__).resolve().parent.parent / "constants" / "jats_2_0_known_tags.json"
DEFAULT_HINTS_PATH = Path(__file__).resolve().parent.parent / "constants" / "template_hints.yaml"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "constants" / "template_schema_ieee.json"

INLINE_TEXT_CHILDREN = ["text", "italic", "sub", "sup", "bold", "inline-formula", "xref"]
SECTION_ROOTS = ("front", "body", "back")

# Children that commonly repeat as list-like content inside a parent.
REPEATABLE_CHILDREN = {
    "p",
    "sec",
    "ref",
    "kwd",
    "list-item",
    "contrib",
    "tr",
    "bio",
    "aff",
    "fig",
    "table-wrap",
    "disp-formula",
    "date",
    "fn",
}

BLOCK_LEVEL_CONTENT_CHILDREN = {
    "p",
    "disp-formula",
    "fig",
    "table-wrap",
    "list",
    "disp-quote",
    "boxed-text",
    "sec",
    "supplementary-material",
    "media",
    "bio",
    "ref",
    "fn",
    "list-item",
    "table",
    "graphic",
    "kwd",
}

METADATA_CHILDREN = {
    "journal-meta",
    "article-meta",
    "title-group",
    "contrib-group",
    "counts",
    "kwd-group",
    "pub-date",
    "abstract",
    "history",
    "self-uri",
    "volume",
    "issue",
    "journal-id",
    "journal-title-group",
    "issn",
    "publisher",
    "article-id",
    "name-alternatives",
    "contrib-id",
    "label",
    "title",
    "caption",
    "ack",
    "ref-list",
    "bio-group",
    "author-comment",
    "person-group",
    "string-name",
    "given-names",
    "surname",
    "email",
    "xref",
    "aff",
    "date",
    "fig-count",
    "table-count",
    "equation-count",
    "ref-count",
    "page-count",
    "colgroup",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "col",
    "fn-group",
    "institution-wrap",
    "institution",
    "publisher-name",
    "element-citation",
    "mixed-citation",
    "pub-id",
    "contrib",
    "year",
    "month",
    "day",
    "string-date",
    "city",
    "country",
    "post-code",
    "inline-formula",
}

INLINE_CONTENT_CHILDREN = {
    "text",
    "italic",
    "sub",
    "sup",
    "bold",
    "inline-formula",
    "xref",
}

STRUCTURAL_CARDINALITY: dict[tuple[str, str], str] = {
    ("article", "front"): "1",
    ("article", "body"): "1",
    ("article", "back"): "1",
    ("front", "journal-meta"): "1",
    ("front", "article-meta"): "1",
    ("title-group", "article-title"): "1",
    ("journal-title-group", "journal-title"): "1",
    ("disp-formula", "tex-math"): "1",
    ("inline-formula", "tex-math"): "1",
    ("fig", "graphic"): "1",
    ("fig", "caption"): "1",
    ("table-wrap", "table"): "1",
    ("list-item", "p"): "1",
    ("pub-date", "year"): "1",
    ("string-name", "surname"): "1",
    ("contrib", "name-alternatives"): "1",
    ("name-alternatives", "string-name"): "1..*",
    ("list", "list-item"): "1..*",
    ("ref-list", "ref"): "1..*",
    ("abstract", "p"): "1..*",
    ("ack", "p"): "1..*",
    ("kwd-group", "kwd"): "1..*",
    ("publisher", "publisher-name"): "1",
}

CARDINALITY_PERMISSIVENESS = {"0..*": 0, "1..*": 1, "0..1": 2, "1": 3}

STRUCTURAL_REQUIRED_PATHS = [
    "front/journal-meta/journal-id",
    "front/article-meta/title-group/article-title",
    "front/article-meta/contrib-group/contrib",
    "front/article-meta/abstract",
    "body/sec",
    "back/ref-list",
]

DEFAULT_LLM_HINTS = LlmHints(
    must_not_hallucinate=["title", "authors", "doi", "abstract"],
    prefer_extract_over_generate=True,
)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _normalize_attributes(attrib: dict[str, str]) -> list[str]:
    names: list[str] = []
    for key in attrib:
        if key == XML_LANG:
            names.append("xml:lang")
        elif key == XLINK_HREF:
            names.append("xlink:href")
        else:
            names.append(_local_name(key))
    return sorted(set(names))


def _more_permissive_cardinality(left: str, right: str) -> str:
    """Return the less restrictive cardinality string."""
    left_rank = CARDINALITY_PERMISSIVENESS.get(left, 2)
    right_rank = CARDINALITY_PERMISSIVENESS.get(right, 2)
    return left if left_rank <= right_rank else right


def _infer_cardinality_from_instances(
    instances: list[dict[str, int]],
    *,
    repeatable_children: set[str] = REPEATABLE_CHILDREN,
) -> dict[str, str]:
    """Infer cardinality from per-parent-instance child observations.

    Rules:
    - Child in every parent instance, max 1 per parent -> ``1``
    - Child in some parent instances -> ``0..1``
    - Child appears multiple times in any parent -> ``1..*``
    - Known list-container children -> ``0..*`` when repeated pattern observed
    """
    if not instances:
        return {}

    total_parents = len(instances)
    all_children: set[str] = set()
    for instance in instances:
        all_children.update(instance.keys())

    cardinality: dict[str, str] = {}
    for child in sorted(all_children):
        parents_with_child = sum(1 for instance in instances if instance.get(child, 0) > 0)
        max_per_parent = max(instance.get(child, 0) for instance in instances)

        if parents_with_child < total_parents:
            cardinality[child] = "0..1"
        elif max_per_parent > 1:
            cardinality[child] = "1..*"
        elif child in repeatable_children and parents_with_child > 0:
            cardinality[child] = "0..*"
        else:
            cardinality[child] = "1"
    return cardinality


def _default_cardinality_for_child(parent_tag: str, child: str) -> str:
    """Infer cardinality for allowed children not seen in the template sample."""
    structural = STRUCTURAL_CARDINALITY.get((parent_tag, child))
    if structural:
        return structural
    if child in BLOCK_LEVEL_CONTENT_CHILDREN or child in REPEATABLE_CHILDREN:
        return "0..*"
    if child in INLINE_CONTENT_CHILDREN:
        return "0..*"
    if child in METADATA_CHILDREN:
        return "0..1"
    return "0..1"


def _ensure_cardinality_coverage(
    parent_tag: str,
    allowed_children: list[str],
    cardinality: dict[str, str],
) -> dict[str, str]:
    """Ensure every allowed child has a cardinality entry."""
    complete = dict(cardinality)
    for child in allowed_children:
        if child not in complete:
            complete[child] = _default_cardinality_for_child(parent_tag, child)
    return complete


def _merge_cardinality(
    known: dict[str, str],
    observed: dict[str, str],
    parent_instance_count: int,
) -> dict[str, str]:
    """Merge known and observed cardinality, preferring permissive values on thin samples."""
    merged = dict(known)
    for child, observed_card in observed.items():
        known_card = merged.get(child)
        if parent_instance_count < 2 and known_card:
            merged[child] = _more_permissive_cardinality(known_card, observed_card)
        elif known_card:
            merged[child] = _more_permissive_cardinality(observed_card, known_card)
        else:
            merged[child] = observed_card
    return merged


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in base + extra:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _load_hints_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError:
            raise ImportError(
                "PyYAML is required to load template_hints.yaml. Install with: pip install pyyaml"
            ) from None
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    return json.loads(text)


def _merge_hints(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge client hints into defaults (union lists; client wins on scalars)."""
    if not override:
        return base
    if not base:
        return override

    merged: dict[str, Any] = dict(base)

    if override.get("required_paths"):
        merged["required_paths"] = _merge_unique(
            base.get("required_paths", []),
            override["required_paths"],
        )

    if override.get("llm_hints"):
        base_llm = dict(base.get("llm_hints", {}))
        override_llm = override["llm_hints"]
        merged_llm = dict(base_llm)
        if override_llm.get("must_not_hallucinate"):
            merged_llm["must_not_hallucinate"] = _merge_unique(
                base_llm.get("must_not_hallucinate", []),
                override_llm["must_not_hallucinate"],
            )
        if "prefer_extract_over_generate" in override_llm:
            merged_llm["prefer_extract_over_generate"] = override_llm["prefer_extract_over_generate"]
        merged["llm_hints"] = merged_llm

    return merged


class TemplateParser:
    """Parse a reference JATS XML template into a :class:`TemplateSchema`."""

    def __init__(
        self,
        template_path: str | Path,
        known_tags_path: str | Path | None = None,
        hints_path: str | Path | None = None,
        dtd_path: str | Path | None = None,
    ) -> None:
        self.template_path = Path(template_path)
        self.known_tags_path = Path(known_tags_path) if known_tags_path else DEFAULT_KNOWN_TAGS_PATH
        self.hints_path = Path(hints_path) if hints_path else None
        self.dtd_path = Path(dtd_path) if dtd_path else None

        if not self.template_path.exists():
            raise FileNotFoundError(f"Template XML not found: {self.template_path}")
        if not self.known_tags_path.exists():
            raise FileNotFoundError(f"Known tags JSON not found: {self.known_tags_path}")

    def parse(self) -> TemplateSchema:
        """Parse template XML and return a merged :class:`TemplateSchema`."""
        known = self._load_known_tags()
        tree = etree.parse(str(self.template_path))
        root = tree.getroot()
        root_name = _local_name(root.tag)

        parent_instances: dict[str, list[dict[str, int]]] = defaultdict(list)
        attributes: dict[str, set[str]] = defaultdict(set)
        section_direct: dict[str, list[str]] = {s: [] for s in SECTION_ROOTS}
        section_descendants: dict[str, set[str]] = {s: set() for s in SECTION_ROOTS}
        path_counts: dict[str, int] = defaultdict(int)
        root_attr_values: dict[str, set[str]] = defaultdict(set)

        for name, value in root.attrib.items():
            attr_name = "xml:lang" if name == XML_LANG else _local_name(name)
            root_attr_values[attr_name].add(value)

        def walk(element: etree._Element, ancestors: list[str], section: str | None) -> None:
            tag = _local_name(element.tag)
            path = "/".join(ancestors + [tag]) if ancestors else tag
            path_counts[path] += 1

            if tag in SECTION_ROOTS:
                section = tag

            if section is not None and tag != section:
                section_descendants[section].add(tag)
                if ancestors and ancestors[-1] == section and tag not in section_direct[section]:
                    section_direct[section].append(tag)

            for attr in _normalize_attributes(element.attrib):
                attributes[tag].add(attr)

            child_counter: dict[str, int] = defaultdict(int)
            for child in element:
                # lxml yields Comment / ProcessingInstruction / Entity nodes too;
                # their .tag is a factory (e.g. etree.Comment), not a str.
                if not isinstance(child.tag, str):
                    continue
                child_name = _local_name(child.tag)
                child_counter[child_name] += 1
                walk(child, ancestors + [tag], section)

            parent_instances[tag].append(dict(child_counter))

        walk(root, [], None)

        tags: dict[str, TagSpec] = {}
        observed_parent_tags = set(parent_instances)
        all_tag_names = set(known.get("tags", {})) | observed_parent_tags | set(attributes)

        for tag_name in sorted(all_tag_names):
            known_tag = known.get("tags", {}).get(tag_name, {})
            instances = parent_instances.get(tag_name, [])
            observed_children = sorted({child for inst in instances for child in inst})
            known_children = known_tag.get("allowed_children", [])
            allowed_children = _merge_unique(known_children, observed_children)

            if known_tag.get("text_content") and not observed_children and tag_name in {
                "p",
                "article-title",
                "title",
            }:
                allowed_children = _merge_unique(allowed_children, INLINE_TEXT_CHILDREN)

            known_attrs = known_tag.get("allowed_attributes", [])
            observed_attrs = sorted(attributes.get(tag_name, set()))
            allowed_attributes = _merge_unique(list(known_attrs), observed_attrs)

            observed_cardinality = _infer_cardinality_from_instances(instances)
            cardinality = _merge_cardinality(
                known_tag.get("cardinality", {}),
                observed_cardinality,
                len(instances),
            )
            cardinality = _ensure_cardinality_coverage(tag_name, allowed_children, cardinality)

            tags[tag_name] = TagSpec(
                allowed_children=allowed_children,
                allowed_attributes=allowed_attributes,
                cardinality=cardinality,
                text_content=bool(known_tag.get("text_content", False)),
            )

        root_attributes = self._build_root_attributes(known, root_attr_values)
        section_boundaries = {
            section: SectionBoundarySpec(
                direct_children=list(section_direct[section]),
                descendants=sorted(section_descendants[section]),
            )
            for section in SECTION_ROOTS
        }
        scope_markers = {
            "front": ["front"],
            "back": ["back"],
            "full": list(SECTION_ROOTS),
        }
        required_paths = self._infer_required_paths(path_counts, tags, known)
        known_attributes = self._merge_known_attributes(known, attributes)
        llm_hints = self._build_llm_hints()

        hints = self._load_hints()
        if hints.get("required_paths"):
            required_paths = _merge_unique(required_paths, hints["required_paths"])
        if hints.get("llm_hints"):
            llm_hints = LlmHints(**{**llm_hints.model_dump(), **hints["llm_hints"]})

        return TemplateSchema(
            template_name=known.get("template_name", "IEEE_JATS_2.0"),
            template_source=str(self.template_path),
            root_tag=root_name,
            root_attributes=root_attributes,
            tags=tags,
            section_boundaries=section_boundaries,
            scope_markers=scope_markers,
            required_paths=required_paths,
            known_attributes=known_attributes,
            llm_hints=llm_hints,
        )

    def to_json(self, output_path: str | Path) -> None:
        """Write ``template_schema.json`` to ``output_path``."""
        schema = self.parse()
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = schema.model_dump(mode="json")
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def load_schema(schema_path: str | Path) -> TemplateSchema:
        """Load an existing schema JSON file."""
        data = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        root_attrs = {
            key: RootAttributeSpec(**value) if isinstance(value, dict) else value
            for key, value in data.get("root_attributes", {}).items()
        }
        tags = {key: TagSpec(**value) for key, value in data.get("tags", {}).items()}
        section_boundaries = {
            key: SectionBoundarySpec(**value) if isinstance(value, dict) else value
            for key, value in data.get("section_boundaries", {}).items()
        }
        llm_hints = LlmHints(**data.get("llm_hints", {}))
        data["root_attributes"] = root_attrs
        data["tags"] = tags
        data["section_boundaries"] = section_boundaries
        data["llm_hints"] = llm_hints
        return TemplateSchema(**data)

    def _load_known_tags(self) -> dict[str, Any]:
        return json.loads(self.known_tags_path.read_text(encoding="utf-8"))

    def _load_hints(self) -> dict[str, Any]:
        defaults = _load_hints_file(DEFAULT_HINTS_PATH) if DEFAULT_HINTS_PATH.exists() else {}
        client_path = self.hints_path
        if client_path and client_path.exists():
            if client_path.resolve() != DEFAULT_HINTS_PATH.resolve():
                return _merge_hints(defaults, _load_hints_file(client_path))
        return defaults

    def _build_llm_hints(self) -> LlmHints:
        hints = self._load_hints()
        if hints.get("llm_hints"):
            return LlmHints(**{**DEFAULT_LLM_HINTS.model_dump(), **hints["llm_hints"]})
        return DEFAULT_LLM_HINTS

    def _build_root_attributes(
        self,
        known: dict[str, Any],
        observed: dict[str, set[str]],
    ) -> dict[str, RootAttributeSpec]:
        specs: dict[str, RootAttributeSpec] = {}
        for name, meta in known.get("root_attributes", {}).items():
            values = list(meta.get("values", []))
            for value in observed.get(name, set()):
                if value not in values:
                    values.append(value)
            specs[name] = RootAttributeSpec(
                required=bool(meta.get("required", False)),
                values=values,
                default=meta.get("default"),
            )
        for name, values in observed.items():
            if name not in specs:
                specs[name] = RootAttributeSpec(required=False, values=sorted(values))
        return specs

    def _merge_known_attributes(
        self,
        known: dict[str, Any],
        observed: dict[str, set[str]],
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {
            tag: list(attrs) for tag, attrs in known.get("known_attributes", {}).items()
        }
        for tag, attrs in observed.items():
            if attrs:
                merged[tag] = _merge_unique(merged.get(tag, []), sorted(attrs))
        return {tag: values for tag, values in merged.items() if values}

    @staticmethod
    def _normalize_required_path(path: str) -> str:
        if path == "article":
            return ""
        if path.startswith("article/"):
            return path[len("article/") :]
        return path

    def _infer_required_paths(
        self,
        path_counts: dict[str, int],
        tags: dict[str, TagSpec],
        known: dict[str, Any],
    ) -> list[str]:
        normalized_counts = {
            self._normalize_required_path(path): count for path, count in path_counts.items()
        }
        required: list[str] = []
        for path, count in sorted(normalized_counts.items()):
            if not path or count != 1:
                continue
            parts = path.split("/")
            tag = parts[-1]
            parent = parts[-2] if len(parts) > 1 else None
            if parent is None:
                continue
            parent_spec = tags.get(parent) or TagSpec(**known.get("tags", {}).get(parent, {}))
            card = parent_spec.cardinality.get(tag, "1")
            if card in {"0..1", "0..*"}:
                continue
            required.append(path)

        structural = [p for p in STRUCTURAL_REQUIRED_PATHS if p in normalized_counts]
        return _merge_unique(structural, required)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse IEEE JATS template XML into template_schema.json")
    parser.add_argument("--template", required=True, help="Path to reference template XML")
    parser.add_argument(
        "--known-tags",
        default=str(DEFAULT_KNOWN_TAGS_PATH),
        help="Path to jats_2_0_known_tags.json",
    )
    parser.add_argument("--hints", default=None, help="Optional template_hints.yaml path")
    parser.add_argument("--dtd", default=None, help="Optional periodicals.dtd path (reserved)")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output schema JSON path")
    return parser


def main() -> None:
    args = _build_cli_parser().parse_args()
    parser = TemplateParser(
        template_path=args.template,
        known_tags_path=args.known_tags,
        hints_path=args.hints,
        dtd_path=args.dtd,
    )
    parser.to_json(args.output)
    print(f"Wrote schema to {args.output}")


if __name__ == "__main__":
    main()
