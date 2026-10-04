"""Cast approval flow through the API: pause -> inspect -> regenerate/edit -> approve -> resume."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_api import wait_for


@pytest.fixture
def client(settings):
    settings.auto_approve = False
    with TestClient(create_app(settings)) as c:
        yield c


def start(client, story):
    job = client.post("/api/jobs", json={"story": story}).json()
    return wait_for(client, job["id"], statuses=("awaiting_approval", "failed", "done"))


def test_job_pauses_for_cast_approval(client, story):
    job = start(client, story)
    assert job["status"] == "awaiting_approval"
    stages = {s["name"]: s for s in job["stages"]}
    assert stages["sheets"]["status"] == "done" and stages["approval"]["status"] == "waiting"
    assert stages["panels"]["status"] == "pending"

    project = client.get(f"/api/jobs/{job['id']}/project").json()
    assert project["status"] == "awaiting_approval" and project["panels"] == []
    main = [c for c in project["characters"] if c["sheets"]["turnaround"]]
    assert main and all(not c["approved"] for c in main)
    for c in main:
        for rel in [c["sheets"]["turnaround"], *c["sheets"]["views"].values(), *c["sheets"]["expression_refs"].values()]:
            assert client.get(project["files_base"] + rel).status_code == 200


def test_regenerate_edit_approve_and_resume(client, story):
    job = start(client, story)
    job_id = job["id"]
    before = client.get(f"/api/jobs/{job_id}/project").json()
    mira = next(c for c in before["characters"] if c["name"] == "Mira")

    # Regenerate the turnaround with a new seed (runs on the worker thread).
    r = client.post(f"/api/jobs/{job_id}/characters/Mira/regenerate", json={"sheet": "turnaround"})
    assert r.status_code == 202
    wait_for(client, job_id, statuses=("awaiting_approval",))
    after = next(c for c in client.get(f"/api/jobs/{job_id}/project").json()["characters"] if c["name"] == "Mira")
    assert after["turnaround_seed"] != mira["turnaround_seed"]
    assert after["expression_seed"] == mira["expression_seed"]
    assert after["version"] == mira["version"] + 1 and after["sheets"]["turnaround"] != mira["sheets"]["turnaround"]
    assert after["status"] == "ready" and not after["approved"]

    # Edit tags -> character needs re-approval.
    r = client.patch(f"/api/jobs/{job_id}/characters/Mira", json={"visual_tags": {"hair": "long white braid"}})
    edited = next(c for c in r.json()["characters"] if c["name"] == "Mira")
    assert edited["visual_tags"]["hair"] == "long white braid" and edited["status"] == "edited"

    # Approving one character isn't enough...
    client.post(f"/api/jobs/{job_id}/characters/Mira/approve", json={"approved": True})
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "awaiting_approval"

    # ...approve all -> the job resumes and finishes.
    assert client.post(f"/api/jobs/{job_id}/approve").status_code == 200
    job = wait_for(client, job_id)
    assert job["status"] == "done", job["error"]
    project = client.get(f"/api/jobs/{job_id}/project").json()
    # The edited tag is used in prompts, and panels got IP-Adapter references.
    mira_prompts = [p for p in project["prompts"] if "Mira" in p["characters"]]
    assert all("long white braid" in p["prompt"] for p in mira_prompts)
    assert any(p["references"] for p in project["prompts"])
    # The approved cast is saved for later chapters.
    assert client.get("/api/projects").json()[0]["project_id"] == job_id


def test_cast_changes_rejected_when_not_waiting(settings, story):
    settings.auto_approve = True
    with TestClient(create_app(settings)) as c:
        job = wait_for(c, c.post("/api/jobs", json={"story": story}).json()["id"])
        assert job["status"] == "done"
        assert c.post(f"/api/jobs/{job['id']}/approve").status_code == 409
        assert c.post(f"/api/jobs/{job['id']}/characters/Mira/regenerate", json={}).status_code == 409


def test_unknown_character_is_404(client, story):
    job = start(client, story)
    assert client.post(f"/api/jobs/{job['id']}/characters/Nobody/approve", json={}).status_code == 404


def test_auto_approve_per_job(client, story):
    job = client.post("/api/jobs", json={"story": story, "auto_approve": True}).json()
    job = wait_for(client, job["id"])
    assert job["status"] == "done"
    trace = client.get(f"/api/jobs/{job['id']}/project").json()["trace"]
    assert any(s["label"] == "Cast approval" and "Auto-approved" in s["notes"][0] for s in trace)
