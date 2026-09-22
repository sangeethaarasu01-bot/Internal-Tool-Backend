import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "data" / "samples" / "access-khan-3639184-proof1.pdf"
SAMPLE_XML = Path(__file__).resolve().parent.parent / "data" / "samples" / "1458251.xml"


@pytest.fixture(scope="module", autouse=True)
def ensure_sample_pdf():
    if not SAMPLE_PDF.exists():
        import sys

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root))
        from scripts.generate_sample_pdf import main

        main()


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_convert_poll(client: TestClient):
    with SAMPLE_PDF.open("rb") as pdf, SAMPLE_XML.open("rb") as tpl:
        up = client.post(
            "/api/upload",
            files={"pdf": ("sample.pdf", pdf, "application/pdf"), "template": ("t.xml", tpl, "application/xml")},
        )
    assert up.status_code == 200
    job_id = up.json()["job_id"]
    conv = client.post(f"/api/convert/{job_id}")
    assert conv.status_code == 200
    for _ in range(60):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "completed"
