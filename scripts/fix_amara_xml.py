"""
One-off post-processor for Amara TCE proof PDF XML (hardcoded metadata).

Prefer pipeline output from ``generate_jats_xml`` + ``relocate_misplaced_front_matter``.
Use this script only when you need a manual repair of an already-generated file.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ET.register_namespace("", "")
ET.register_namespace("ali", "http://www.niso.org/schemas/ali/1.0/")
ET.register_namespace("mml", "http://www.w3.org/1998/Math/MathML")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")


def fix_xml(input_path: str, output_path: str) -> None:
    tree = ET.parse(input_path)
    root = tree.getroot()

    front = root.find("front")
    body = root.find("body")
    if front is None or body is None:
        raise ValueError("Missing front or body")
    meta = front.find("article-meta")
    if meta is None:
        raise ValueError("Missing article-meta")

    loose_paras = [p for p in body if p.tag == "p"]

    print(f"Found {len(loose_paras)} loose paragraphs in body")
    for index, para in enumerate(loose_paras):
        text = "".join(para.itertext()).strip()
        print(f"  [{index}] ({len(text)} chars) {text[:100]}...")

    title_el = meta.find(".//article-title")
    if title_el is None:
        raise ValueError("Missing article-title")

    title_text = (
        "Split Multi-Task Federated Learning for Battery Health and "
        "Capacity Estimation in Electric Vehicles"
    )
    title_found = False
    for para in loose_paras[:]:
        text = "".join(para.itertext()).strip()
        if "Split Multi-Task Federated Learning" in text and "Battery Health" in text:
            title_el.text = title_text
            body.remove(para)
            loose_paras.remove(para)
            title_found = True
            print(f"TITLE SET: {title_text}")
            break
    if not title_found:
        print("WARNING: Title paragraph not found in body")

    abstract_el = meta.find("abstract")
    if abstract_el is None:
        abstract_el = ET.SubElement(meta, "abstract")
    abstract_p = abstract_el.find("p")
    if abstract_p is None:
        abstract_p = ET.SubElement(abstract_el, "p")

    full_abstract = (
        "The rapid adoption of electric vehicles (EVs) has heightened the need "
        "for advanced diagnostic frameworks to ensure the safety, reliability, "
        "and longevity of battery systems. Batteries, as the cornerstone of EV "
        "performance, are susceptible to capacity degradation, thermal instability, "
        "and anomalies that compromise efficiency and safety. Traditional diagnostic "
        "approaches, relying on physics-based models and heuristic thresholds, often "
        "fail to address the complexity and variability of real-world EV operations, "
        "necessitating scalable, efficient, and privacy-preserving solutions. This "
        "paper presents a Split Multi-Task Federated Learning (SMTFL) framework "
        "that leverages a Transformer-based architecture to address the dual "
        "challenges of battery health anomaly detection and capacity estimation. "
        "By combining the efficiency of split learning with the collaborative "
        "benefits of federated learning, the proposed system enables EVs to train "
        "and share partial model updates while retaining sensitive data locally. "
        "Experimental results on a recent large-scale EV dataset demonstrate the "
        "superior performance of the SMTFL framework, achieving an accuracy of "
        "98.9% for battery health anomaly detection and a mean absolute error "
        "(MAE) of 0.32 Ah for capacity estimation, corresponding to a relative "
        "error of approximately 1.80%, significantly outperforming state-of-the-art "
        "approaches. By training a single model for both tasks and performing "
        "computations during charging sessions, the framework minimizes energy "
        "consumption and computational overhead, ensuring practicality for "
        "large-scale deployment in real-world EV systems."
    )
    abstract_p.text = full_abstract
    for child in list(abstract_p):
        abstract_p.remove(child)
    print(f"ABSTRACT SET ({len(full_abstract)} chars)")

    for para in loose_paras[:]:
        text = "".join(para.itertext()).strip()
        if (
            "rapid adoption" in text
            or "heightened the need" in text
            or "The rapid adoption" in text
            or "Machine learning has emerged" in text
        ):
            body.remove(para)
            loose_paras.remove(para)
            print(f"Removed abstract fragment: {text[:60]}...")

    kwd_group = meta.find("kwd-group")
    if kwd_group is None:
        kwd_group = ET.SubElement(meta, "kwd-group")
        kwd_group.set("kwd-group-type", "AuthorFree")
    for kwd in list(kwd_group.findall("kwd")):
        kwd_group.remove(kwd)

    keywords = [
        "Electric vehicle",
        "battery state of health",
        "state of charge (SOC)",
        "battery management system (BMS)",
        "split federated learning",
        "transformer",
    ]
    for kw in keywords:
        kwd = ET.SubElement(kwd_group, "kwd")
        kwd.text = kw
    print(f"KEYWORDS SET: {len(keywords)} keywords")

    for para in list(loose_paras):
        text = "".join(para.itertext()).strip()
        if (
            re.match(r"^IEEE\s+TRANSACTIONS", text, re.I)
            or re.match(r"^\d+\s+IEEE\s+TRANSACTIONS", text, re.I)
            or text.startswith("AMARA KORBA et al")
        ):
            body.remove(para)
            print(f"Removed running header: {text[:60]}...")

    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    if not input_file:
        outputs_dir = Path("outputs")
        xmls = sorted(
            outputs_dir.glob("tce-amarakorba*.xml"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if xmls:
            input_file = str(xmls[0])
            print(f"Using latest: {input_file}")

    if not input_file:
        print("Usage: python scripts/fix_amara_xml.py <input.xml> [output.xml]")
        sys.exit(1)

    output_file = (
        sys.argv[2] if len(sys.argv) > 2 else str(input_file).replace(".xml", "_FIXED.xml")
    )
    fix_xml(input_file, output_file)
