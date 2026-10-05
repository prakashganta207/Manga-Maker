import time

import pytest
from fastapi.testclient import TestClient

from app.agents.graph import STAGES
from app.main import create_app
from app.providers.base import LLMProvider, ProviderError


def wait_for(client, job_id, statuses=("done", "failed"), timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in statuses and not job.get("busy"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job did not reach {statuses} in time")


@pytest.fixture
def client(settings):
    settings.auto_approve = True
    with TestClient(create_app(settings)) as c:
        yield c


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["providers"]["llm"] == "mock" and body["providers"]["image"] == "mock"


def test_full_job_produces_png_and_pdf(client, story):
    response = client.post("/api/jobs", json={"story": story})
    assert response.status_code == 202
    job = response.json()
    assert job["status"] in ("queued", "running")
    assert [s["name"] for s in job["stages"]] == STAGES

    job = wait_for(client, job["id"])
    assert job["status"] == "done", job["error"]
    assert job["progress"] == 1.0 and all(s["status"] == "done" for s in job["stages"])

    result = job["result"]
    png = client.get(result["outputs"]["rtl"]["pages"][0])
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = client.get(result["outputs"]["ltr"]["pdf"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    project = client.get(f"/api/jobs/{job['id']}/project").json()
    assert project["status"] == "done" and project["files_base"] == f"/files/{job['id']}/"
    agents = [step["agent"] for step in project["trace"]]
    assert agents[:3] == ["writer", "writer", "director"] and "character_designer" in agents
    assert project["beat_sheet"]["beats"] and project["director"]["pages"]
    assert client.get(project["files_base"] + project["panels"][0]["image"]).status_code == 200

    assert client.get("/api/jobs").json()[0]["id"] == job["id"]


def test_layouts_and_samples_endpoints(client):
    layouts = client.get("/api/layouts").json()
    assert len(layouts) >= 8 and {"id", "panels", "slots"} <= set(layouts[0])
    samples = client.get("/api/samples").json()
    assert isinstance(samples, list)


def test_short_story_is_rejected(client):
    assert client.post("/api/jobs", json={"story": "Too short"}).status_code == 422


def test_bad_project_id_is_rejected(client, story):
    assert client.post("/api/jobs", json={"story": story, "project_id": "../etc"}).status_code == 422


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/project").status_code == 404


def test_path_traversal_blocked(client):
    assert client.get("/files/../app/config.py").status_code == 404


class BrokenLLM(LLMProvider):
    name = "broken"

    def generate_json(self, **kwargs):
        raise ProviderError("service unavailable")


def test_failed_job_reports_error(settings, story):
    with TestClient(create_app(settings, llm=BrokenLLM())) as c:
        job = wait_for(c, c.post("/api/jobs", json={"story": story}).json()["id"])
        project = c.get(f"/api/jobs/{job['id']}/project").json()
    assert job["status"] == "failed" and "service unavailable" in job["error"]
    assert job["stages"][0]["name"] == "writer" and job["stages"][0]["status"] == "failed"
    # The failed agent attempt is still visible in the timeline.
    assert project["status"] == "failed" and project["trace"][0]["status"] == "failed"


def test_jobs_are_reloaded_from_disk_after_restart(settings, story):
    from app.agents.pipeline import new_project, run_project
    settings.auto_approve = True
    job_dir = settings.output_dir / "oldjob"
    run_project(new_project(story, "oldjob", settings), settings=settings, job_dir=job_dir)
    app = create_app(settings)
    with TestClient(app) as client:          # startup = "server restart"
        job = client.get("/api/jobs/oldjob").json()
        assert job["status"] == "done"
        assert job["result"]["outputs"]["rtl"]["pages"][0].startswith("/files/oldjob/")
        assert client.get("/api/jobs/oldjob/project").json()["job_id"] == "oldjob"
