"""
Full heuristic-mode extraction workflow for IEEE XML Converter.
No LLM. Uses template-driven semantic mapping.

Place this file in: backend/
Run: python extract_kakichi.py
"""

import json
import time
import requests
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================
BASE_URL = "http://localhost:8000"
PDF_PATH = r"C:\Users\ponar\Downloads\xml file\New folder\1467636_view\access-kakichi-3657695-proof.pdf1.pdf"
TEMPLATE_PATH = r"C:\Users\ponar\Downloads\xml file\New folder\1467974 (2)\1467974.xml"
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================
# STEP 1: UPLOAD PDF
# ============================================================
def step1_upload_pdf():
    print("\n" + "="*60)
    print("STEP 1: Upload PDF")
    print("="*60)
    
    with open(PDF_PATH, "rb") as f:
        files = {"file": (Path(PDF_PATH).name, f, "application/pdf")}
        r = requests.post(f"{BASE_URL}/api/extractions/", files=files)
    
    if r.status_code != 200:
        print(f"❌ Upload failed: {r.status_code} - {r.text}")
        return None
    
    data = r.json()
    extraction_id = data["extraction_id"]
    print(f"✅ Extraction ID: {extraction_id}")
    print(f"   Status: {data['status']}")
    return extraction_id


# ============================================================
# STEP 2: POLL STATUS
# ============================================================
def step2_wait_for_completion(extraction_id, max_wait=300):
    print("\n" + "="*60)
    print("STEP 2: Wait for extraction completion")
    print("="*60)
    
    start = time.time()
    last_step = None
    
    while time.time() - start < max_wait:
        r = requests.get(f"{BASE_URL}/api/extractions/{extraction_id}")
        if r.status_code != 200:
            print(f"❌ Status check failed: {r.status_code}")
            return False
        
        data = r.json()
        status = data["status"]
        progress = data["progress"]
        step = data["current_step"]
        
        if step != last_step:
            print(f"   [{progress}%] {step} - {status}")
            last_step = step
        
        if status == "completed":
            print(f"✅ Extraction complete!")
            return True
        elif status == "failed":
            print(f"❌ Extraction failed: {data.get('error_message')}")
            return False
        
        time.sleep(3)
    
    print(f"⚠️ Timeout after {max_wait}s")
    return False


# ============================================================
# STEP 3: UPLOAD TEMPLATE
# ============================================================
def step3_upload_template(extraction_id):
    print("\n" + "="*60)
    print("STEP 3: Upload template XML")
    print("="*60)
    
    with open(TEMPLATE_PATH, "rb") as f:
        files = {"file": (Path(TEMPLATE_PATH).name, f, "application/xml")}
        r = requests.post(
            f"{BASE_URL}/api/extractions/{extraction_id}/template",
            files=files,
        )
    
    if r.status_code != 200:
        print(f"❌ Template upload failed: {r.status_code} - {r.text}")
        return None
    
    data = r.json()
    template_id = data["template_id"]
    print(f"✅ Template ID: {template_id}")
    print(f"   Template name: {data['schema'].get('template_name')}")
    print(f"   Root tag: {data['schema'].get('root_tag')}")
    print(f"   Format: {data['schema'].get('template_format')}")
    return template_id


# ============================================================
# STEP 4: HEURISTIC SEMANTIC MAP (no LLM)
# ============================================================
def step4_semantic_map(extraction_id):
    print("\n" + "="*60)
    print("STEP 4: Semantic mapping (HEURISTIC — no LLM)")
    print("="*60)
    
    payload = {"scope": "full"}
    r = requests.post(
        f"{BASE_URL}/api/extractions/{extraction_id}/semantic-map",
        json=payload,
    )
    
    if r.status_code != 200:
        print(f"❌ Semantic map failed: {r.status_code} - {r.text}")
        return None
    
    data = r.json()
    print(f"✅ Mapping complete")
    print(f"   Document ID: {data['document_id']}")
    print(f"   Scope: {data['scope']}")
    print(f"   Prompt version: {data.get('prompt_version', 'N/A')}")
    print(f"   Mapping source: {data.get('mapping_source', 'N/A')}")
    
    unmapped = data.get("unmapped_content", [])
    warnings = data.get("warnings", [])
    print(f"   Unmapped content: {len(unmapped)} items")
    print(f"   Warnings: {len(warnings)}")
    
    for w in warnings[:5]:
        print(f"     ⚠️ {w}")
    
    # Save to file
    map_file = OUTPUT_DIR / f"{extraction_id}_semantic_map.json"
    with open(map_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"   Saved: {map_file}")
    return data


# ============================================================
# STEP 5: GENERATE XML (HEURISTIC, no LLM)
# ============================================================
def step5_generate_xml(extraction_id):
    print("\n" + "="*60)
    print("STEP 5: Generate XML (HEURISTIC — no LLM)")
    print("="*60)
    
    payload = {
        "scope": "full",
        "use_llm": False,        # heuristic mode
        "llm_fallback": False,   # no LLM fallback
        "output_format": "ieee_jats",  # or "auto"
    }
    r = requests.post(
        f"{BASE_URL}/api/extractions/{extraction_id}/generate-xml",
        json=payload,
    )
    
    if r.status_code != 200:
        print(f"❌ Generate XML failed: {r.status_code} - {r.text}")
        return None
    
    data = r.json()
    print(f"✅ XML generated")
    print(f"   Document ID: {data['document_id']}")
    print(f"   Output format: {data['output_format']}")
    print(f"   Mapping source: {data['mapping_source']}")
    print(f"   Output filename: {data.get('output_filename', 'N/A')}")
    print(f"   Unmapped content: {data['unmapped_content_count']}")
    print(f"   Warnings: {len(data['warnings'])}")
    
    # Save XML content directly
    xml_file = OUTPUT_DIR / f"{extraction_id}_output.xml"
    with open(xml_file, "w", encoding="utf-8") as f:
        f.write(data["xml_content"])
    print(f"   Saved: {xml_file}")
    
    # Save full response
    resp_file = OUTPUT_DIR / f"{extraction_id}_generate_response.json"
    with open(resp_file, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in data.items() if k != "xml_content"}, f, indent=2)
    print(f"   Saved: {resp_file}")
    return data


# ============================================================
# STEP 6: DOWNLOAD XML
# ============================================================
def step6_download_xml(extraction_id):
    print("\n" + "="*60)
    print("STEP 6: Download XML")
    print("="*60)
    
    r = requests.get(f"{BASE_URL}/api/extractions/{extraction_id}/download-xml")
    
    if r.status_code != 200:
        print(f"❌ Download failed: {r.status_code} - {r.text}")
        return None
    
    xml_file = OUTPUT_DIR / f"{extraction_id}_downloaded.xml"
    with open(xml_file, "wb") as f:
        f.write(r.content)
    print(f"✅ Downloaded: {xml_file}")
    print(f"   Size: {len(r.content)} bytes")
    return xml_file


# ============================================================
# MAIN
# ============================================================
def main():
    print("="*60)
    print("IEEE XML Converter — Heuristic Mode (No LLM)")
    print("="*60)
    
    # Step 1
    extraction_id = step1_upload_pdf()
    if not extraction_id:
        return
    
    # Step 2
    if not step2_wait_for_completion(extraction_id):
        return
    
    # Step 3
    template_id = step3_upload_template(extraction_id)
    if not template_id:
        return
    
    # Step 4 — heuristic semantic map
    step4_semantic_map(extraction_id)
    
    # Step 5 — heuristic XML generation
    result = step5_generate_xml(extraction_id)
    if not result:
        return
    
    # Step 6 — download
    step6_download_xml(extraction_id)
    
    # Preview XML (first 3000 chars)
    print("\n" + "="*60)
    print("XML PREVIEW (first 3000 chars)")
    print("="*60)
    print(result["xml_content"][:3000])
    
    print("\n" + "="*60)
    print("✅ DONE!")
    print(f"   Extraction ID: {extraction_id}")
    print(f"   Output dir: {OUTPUT_DIR.absolute()}")
    print("="*60)


if __name__ == "__main__":
    main()