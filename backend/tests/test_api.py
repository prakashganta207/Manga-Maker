import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import LLMProvider, ProviderError


def wait_for(client, job_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["providers"] == {"llm": "mock", "image": "mock"}


def test_full_job_produces_png_and_pdf(client, story):
    response = client.post("/api/jobs", json={"story": story})
    assert response.status_code == 202
    job = response.json()
    assert job["status"] in ("queued", "running")
    assert [s["name"] for s in job["stages"]] == ["script", "characters", "panels", "layout", "export"]

    job = wait_for(client, job["id"])
    assert job["status"] == "done", job["error"]
    assert job["progress"] == 1.0
    assert all(s["status"] == "done" for s in job["stages"])

    result = job["result"]
    page_url = result["outputs"]["rtl"]["pages"][0]
    png = client.get(page_url)
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = client.get(result["outputs"]["ltr"]["pdf"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(result["characters"][0]["reference_image_url"]).status_code == 200
    assert client.get(result["script_url"]).json()["title"] == result["title"]

    listing = client.get("/api/jobs").json()
    assert listing[0]["id"] == job["id"]


def test_short_story_is_rejected(client):
    assert client.post("/api/jobs", json={"story": "Too short"}).status_code == 422


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_path_traversal_blocked(client):
    assert client.get("/files/../app/config.py").status_code == 404


class BrokenLLM(LLMProvider):
    name = "broken"

    def generate_json(self, **kwargs):
        raise ProviderError("service unavailable")


def test_failed_job_reports_error(settings, story):
    with TestClient(create_app(settings, llm=BrokenLLM())) as c:
        job = wait_for(c, c.post("/api/jobs", json={"story": story}).json()["id"])
    assert job["status"] == "failed"
    assert "service unavailable" in job["error"]
    script_stage = job["stages"][0]
    assert script_stage["name"] == "script" and script_stage["status"] == "failed"
