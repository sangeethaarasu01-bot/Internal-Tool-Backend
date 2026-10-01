import json
import re
import sys
from pathlib import Path

from app.agent.xml_generator import _generate_from_template_dom
from app.models.mapping_plan import MappingPlan
from app.models.paper import PaperData


def broken(xml: str) -> list[str]:
    xref_rids = re.findall(r'<xref[^>]+rid="([^"]+)"', xml)
    id_attrs = set(re.findall(r'\bid="([^"]+)"', xml))
    return sorted({r for r in xref_rids if r not in id_attrs})


def main() -> None:
    job = sys.argv[1] if len(sys.argv) > 1 else "ed6edab4-4ba4-4990-834d-9e283e1ec078"
    base = Path("data/uploads") / job
    tpl = (base / "template.xml").read_text(encoding="utf-8", errors="replace")
    paper_path = Path("data/outputs") / f"{job}_paper.json"
    paper = PaperData.model_validate(json.loads(paper_path.read_text(encoding="utf-8")))

    tb = broken(tpl)
    print(f"template broken xrefs: {len(tb)}")
    if tb:
        print(" sample:", tb[:15])

    out = _generate_from_template_dom(tpl, paper, MappingPlan(mappings=[]))
    ob = broken(out)
    print(f"output broken xrefs: {len(ob)}")
    print(ob)


if __name__ == "__main__":
    main()
