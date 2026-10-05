"""Phase 4 M4: stored lettering layers + editor API."""

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agents.pipeline import new_project, run_project
from app.agents.state import Bubble, PageLettering
from app.main import create_app
from app.pipeline.bubbles import fit_text, to_fraction, to_pixels
from app.geometry import Rect


@pytest.fixture
def client(settings, story):
    settings.auto_approve = True
    run_project(new_project(story, "ed", settings), settings=settings, job_dir=settings.output_dir / "ed")
    with TestClient(create_app(settings)) as c:
        yield c


def test_pipeline_stores_lettering_layers(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "j", settings), settings=settings, job_dir=tmp_path)
    assert [pl.page for pl in project.lettering] == [p.page_number for p in project.page_plan.pages]
    bubbles = [b for pl in project.lettering for b in pl.bubbles]
    dialogue = [d for _, pn in project.page_plan.all_panels() for d in pn.dialogue]
    assert len([b for b in bubbles if b.kind in ("speech", "shout")]) == len(dialogue)
    assert all(0 <= b.x <= 1 and 0 <= b.y <= 1 for b in bubbles)
    assert all(b.text for b in bubbles)


def test_fraction_round_trip():
    panel = Rect(100, 200, 400, 300)
    box = Rect(140, 230, 120, 60)
    x, y, w, h = to_fraction(box, panel)
    assert to_pixels(Bubble(id="a", panel=1, x=x, y=y, w=w, h=h), panel) == box


def test_fit_text_shrinks_font_for_small_bubbles():
    from PIL import ImageDraw
    draw = ImageDraw.Draw(Image.new("L", (10, 10)))
    _, big = fit_text("speech", "HELLO THERE FRIEND", Rect(0, 0, 400, 200), 26, "", draw)
    lines, small = fit_text("speech", "HELLO THERE FRIEND", Rect(0, 0, 120, 70), 26, "", draw)
    assert big == 26 and small < 26 and len(lines) >= 2


def test_editor_page_payload(client):
    data = client.get("/api/jobs/ed/pages/1/editor").json()
    assert data["width"] == 1240 and data["direction"] == "rtl"
    assert data["panels"] and all(p["image"] for p in data["panels"])
    assert data["lettering"]["bubbles"]
    ltr = client.get("/api/jobs/ed/pages/1/editor", params={"direction": "ltr"}).json()
    # Mirrored page: same panels, different x positions (unless symmetric).
    assert [p["panel"] for p in ltr["panels"]] == [p["panel"] for p in data["panels"]]
    assert client.get("/api/jobs/ed/pages/9/editor").status_code == 404


def test_save_lettering_rerenders_page(client, settings):
    data = client.get("/api/jobs/ed/pages/1/editor").json()
    page_file = settings.output_dir / "ed" / data["rendered"]
    before = page_file.read_bytes()
    bubbles = data["lettering"]["bubbles"]
    bubbles[0].update(text="EDITED BY A HUMAN", kind="thought", x=0.1, y=0.1)
    bubbles.append({"id": "new1", "panel": data["panels"][0]["panel"], "kind": "narration", "text": "Meanwhile...",
                    "x": 0.5, "y": 0.7, "w": 0.4, "h": 0.15})
    response = client.put("/api/jobs/ed/pages/1/lettering", json={"bubbles": bubbles})
    assert response.status_code == 200, response.text
    saved = response.json()["lettering"]
    assert saved["source"] == "edited"
    assert saved["bubbles"][0]["text"] == "EDITED BY A HUMAN" and saved["bubbles"][-1]["id"] == "new1"
    assert page_file.read_bytes() != before
    project = client.get("/api/jobs/ed/project").json()
    assert project["lettering"][0]["source"] == "edited"


def test_save_rejects_unknown_panels_and_duplicate_ids(client):
    bad = {"bubbles": [{"id": "a", "panel": 99, "text": "x"}]}
    assert client.put("/api/jobs/ed/pages/1/lettering", json=bad).status_code == 422
    dup = {"bubbles": [{"id": "a", "panel": 1, "text": "x"}, {"id": "a", "panel": 1, "text": "y"}]}
    assert client.put("/api/jobs/ed/pages/1/lettering", json=dup).status_code == 422


def test_reset_restores_automatic_layout(client):
    auto = client.get("/api/jobs/ed/pages/1/editor").json()["lettering"]["bubbles"]
    client.put("/api/jobs/ed/pages/1/lettering", json={"bubbles": []})
    assert client.get("/api/jobs/ed/pages/1/editor").json()["lettering"]["bubbles"] == []
    reset = client.post("/api/jobs/ed/pages/1/lettering/reset").json()["lettering"]
    assert reset["source"] == "auto" and len(reset["bubbles"]) == len(auto)


def test_editing_requires_finished_job(client):
    client.app.state.manager.get("ed").status = "running"
    assert client.put("/api/jobs/ed/pages/1/lettering", json={"bubbles": []}).status_code == 409


def test_old_projects_without_layers_get_planned_layers(client, settings):
    from app.agents.state import MangaProject
    job_dir = settings.output_dir / "ed"
    project = MangaProject.load(job_dir)
    project.lettering = []
    project.save(job_dir)
    data = client.get("/api/jobs/ed/pages/1/editor").json()
    assert data["lettering"]["bubbles"] and data["lettering"]["source"] == "auto"
