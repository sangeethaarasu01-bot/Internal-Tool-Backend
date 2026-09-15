"""Tests for template_parser.py — IEEE JATS template schema extraction."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.models.template_schema import TemplateSchema
from app.services.template_parser import TemplateParser, _load_hints_file, _merge_hints

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_XML = ROOT / "tests" / "fixtures" / "1458242.xml"
KNOWN_TAGS = ROOT / "app" / "constants" / "jats_2_0_known_tags.json"
HINTS_YAML = ROOT / "app" / "constants" / "template_hints.yaml"
OUTPUT_SCHEMA = ROOT / "app" / "constants" / "template_schema_ieee.json"


@pytest.fixture
def schema() -> TemplateSchema:
    return TemplateParser(FIXTURE_XML, known_tags_path=KNOWN_TAGS).parse()


def test_parse_returns_schema_with_root_article(schema: TemplateSchema) -> None:
    assert schema.root_tag == "article"
    assert schema.template_name == "IEEE_JATS_2.0"
    assert "article" in schema.tags
    assert schema.tags["article"].allowed_children[:3] == ["front", "body", "back"]


def test_front_boundary_direct_children(schema: TemplateSchema) -> None:
    front = schema.section_boundaries["front"]
    assert front.direct_children == ["journal-meta", "article-meta"]
    assert "front" not in front.direct_children
    assert "abstract" in front.descendants
    assert "article-title" in front.descendants


def test_back_boundary_includes_ref_list_and_bio_group(schema: TemplateSchema) -> None:
    back = schema.section_boundaries["back"]
    assert "back" not in back.direct_children
    assert "ref-list" in back.direct_children
    assert "bio-group" in back.descendants
    assert "ack" in back.descendants
    assert "ref" in back.descendants


def test_disp_formula_cardinality_label_optional(schema: TemplateSchema) -> None:
    spec = schema.tags["disp-formula"]
    assert "tex-math" in spec.allowed_children
    assert "label" in spec.allowed_children
    assert spec.cardinality.get("tex-math") == "1"
    assert spec.cardinality.get("label") == "0..1"


def test_inline_formula_requires_tex_math(schema: TemplateSchema) -> None:
    spec = schema.tags["inline-formula"]
    assert "tex-math" in spec.allowed_children
    assert spec.cardinality.get("tex-math") == "1"


def test_graphic_has_xlink_href_attribute(schema: TemplateSchema) -> None:
    graphic_attrs = schema.tags["graphic"].allowed_attributes
    known_graphic = schema.known_attributes.get("graphic", [])
    assert "xlink:href" in graphic_attrs or "xlink:href" in known_graphic


def test_scope_markers_front_returns_only_front(schema: TemplateSchema) -> None:
    assert schema.scope_markers["front"] == ["front"]
    assert schema.get_scope_sections("front") == ["front"]


def test_scope_markers_full_returns_all_three(schema: TemplateSchema) -> None:
    assert schema.scope_markers["full"] == ["front", "body", "back"]
    assert schema.get_scope_sections("full") == ["front", "body", "back"]


def test_required_paths_includes_structural_paths(schema: TemplateSchema) -> None:
    required = set(schema.required_paths)
    assert "front/article-meta/title-group/article-title" in required
    assert "front/journal-meta/journal-id" in required
    assert "front/article-meta/contrib-group/contrib" in required
    assert "front/article-meta/abstract" in required
    assert "body/sec" in required
    assert "back/ref-list" in required


def test_schema_is_json_serializable(schema: TemplateSchema) -> None:
    payload = schema.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["root_tag"] == "article"
    assert "tags" in decoded
    assert decoded["tags"]["disp-formula"]["cardinality"]["label"] == "0..1"


def test_llm_hints_present(schema: TemplateSchema) -> None:
    assert "title" in schema.llm_hints.must_not_hallucinate
    assert schema.llm_hints.prefer_extract_over_generate is True


def test_load_schema_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "schema.json"
    parser = TemplateParser(FIXTURE_XML, known_tags_path=KNOWN_TAGS)
    parser.to_json(out)
    loaded = TemplateParser.load_schema(out)
    assert loaded.root_tag == "article"
    assert loaded.tags["disp-formula"].cardinality["label"] == "0..1"
    assert loaded.section_boundaries["front"].direct_children == ["journal-meta", "article-meta"]
    assert loaded.llm_hints.must_not_hallucinate


def test_supplementary_material_parent_is_body_not_article(schema: TemplateSchema) -> None:
    article_children = schema.tags["article"].allowed_children
    body_children = schema.tags["body"].allowed_children
    assert "supplementary-material" not in article_children
    assert "supplementary-material" in body_children


def test_cli_generates_output_schema(tmp_path: Path) -> None:
    out = tmp_path / "schema_from_cli.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.services.template_parser",
            "--template",
            str(FIXTURE_XML),
            "--known-tags",
            str(KNOWN_TAGS),
            "--output",
            str(out),
        ],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Wrote schema to" in result.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["root_tag"] == "article"
    assert data["tags"]["disp-formula"]["cardinality"]["label"] == "0..1"


def test_template_hints_yaml_merges_required_paths() -> None:
    parser = TemplateParser(FIXTURE_XML, known_tags_path=KNOWN_TAGS, hints_path=HINTS_YAML)
    schema = parser.parse()
    assert "front/article-meta/contrib-group/contrib" in schema.required_paths


def test_template_hints_merge_defaults_with_client_override(tmp_path: Path) -> None:
    default_yaml = tmp_path / "default_hints.yaml"
    default_yaml.write_text(
        "required_paths:\n  - path/A\n  - path/B\n  - path/C\n",
        encoding="utf-8",
    )
    client_yaml = tmp_path / "client_hints.yaml"
    client_yaml.write_text("required_paths:\n  - path/D\n", encoding="utf-8")

    defaults = _load_hints_file(default_yaml)
    client = _load_hints_file(client_yaml)
    merged = _merge_hints(defaults, client)

    assert set(merged["required_paths"]) == {"path/A", "path/B", "path/C", "path/D"}


def test_body_cardinality_covers_all_allowed_children(schema: TemplateSchema) -> None:
    body = schema.tags["body"]
    missing = set(body.allowed_children) - set(body.cardinality.keys())
    assert not missing, f"Missing: {missing}"
    assert set(body.cardinality.keys()) == set(body.allowed_children)


def test_every_tag_cardinality_covers_allowed_children(schema: TemplateSchema) -> None:
    for tag_name, tag_spec in schema.tags.items():
        missing = set(tag_spec.allowed_children) - set(tag_spec.cardinality.keys())
        assert not missing, f"{tag_name} missing cardinality for: {missing}"


def test_parse_skips_xml_comments_and_processing_instructions(tmp_path: Path) -> None:
    """Comment/PI children have non-str .tag (lxml factories); must not crash walk()."""
    template = tmp_path / "template_with_comment.xml"
    template.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<article dtd-version="2.0" xml:lang="eng">
  <!-- IEEE JATS reference template metadata -->
  <?xml-stylesheet type="text/xsl" href="article.xsl"?>
  <front>
    <journal-meta>
      <journal-title-group>
        <journal-title>IEEE Sensors Journal</journal-title>
      </journal-title-group>
    </journal-meta>
    <article-meta>
      <title-group>
        <article-title>Sample Title</article-title>
      </title-group>
    </article-meta>
  </front>
  <body><sec><title>Intro</title><p>Text.</p></sec></body>
  <back><ref-list><ref id="ref1"><label>[1]</label></ref></ref-list></back>
</article>
""",
        encoding="utf-8",
    )
    schema = TemplateParser(template, known_tags_path=KNOWN_TAGS).parse()
    assert schema.root_tag == "article"
    assert schema.tags["article"].allowed_children[:3] == ["front", "body", "back"]
    assert "journal-title" in schema.section_boundaries["front"].descendants


def test_client_hints_file_merges_with_builtin_defaults(tmp_path: Path) -> None:
    client_yaml = tmp_path / "client_b_hints.yaml"
    client_yaml.write_text(
        "required_paths:\n  - custom/client-only-path\n",
        encoding="utf-8",
    )
    parser = TemplateParser(FIXTURE_XML, known_tags_path=KNOWN_TAGS, hints_path=client_yaml)
    schema = parser.parse()
    assert "custom/client-only-path" in schema.required_paths
    assert "front/journal-meta/journal-id" in schema.required_paths
    assert "front/article-meta/contrib-group/contrib" in schema.required_paths
