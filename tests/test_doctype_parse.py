"""DOCTYPE stripping fixes lxml parse errors on IEEE templates."""

from lxml import etree

from app.utils.xml_helpers import (
    extract_doctype_declaration,
    normalize_doctype_spacing,
    parse_xml_string,
    strip_xml_prolog_for_parse,
)

MULTILINE_DOCTYPE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//IEEE//DTD IEEE JATS Interchange DTD with MathML3 v1.3 20210610//EN"
"ieee-jats-interchange.dtd">
<article><front><article-meta><title-group>
<article-title>Sample Title</article-title>
</title-group></article-meta></front></article>"""


def test_extract_multiline_doctype() -> None:
    dt = extract_doctype_declaration(MULTILINE_DOCTYPE)
    assert dt is not None
    assert "PUBLIC" in dt
    assert dt.strip().endswith(">")


def test_parse_template_with_multiline_doctype() -> None:
    root = parse_xml_string(MULTILINE_DOCTYPE)
    titles = root.xpath(".//*[local-name()='article-title']")
    assert titles and (titles[0].text or "").strip() == "Sample Title"


def test_normalize_doctype_adds_space_between_literals() -> None:
    broken = '<!DOCTYPE article PUBLIC "-//IEEE//EN""file.dtd">'
    fixed = normalize_doctype_spacing(broken)
    assert 'EN" "' in fixed or 'EN" "file' in fixed
    body, dt = strip_xml_prolog_for_parse(fixed + "<article/>")
    etree.fromstring(body.encode("utf-8"))
