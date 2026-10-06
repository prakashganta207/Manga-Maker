"""Phase 5 M12: demo mode loads a pre-generated series instantly."""

import json
import shutil

from fastapi.testclient import TestClient

from app import routes_demo
from app.agents.pipeline import new_project, run_project
from app.main import create_app


def test_demo_mode_loads_series_without_generation(settings, story, tmp_path, monkeypatch):
    # Build a tiny demo folder the way scripts/make_demo.py does.
    settings.auto_approve = True
    source = tmp_path / "source"
    source.mkdir()
    settings.output_dir = source
    run_project(new_project(story, "demo-ch1", settings), settings=settings, job_dir=source / "demo-ch1")
    demo = tmp_path / "demo"
    shutil.copytree(source / "demo-ch1", demo / "jobs" / "demo-ch1")
    shutil.copytree(source / "projects", demo / "projects")
    (demo / "demo.json").write_text(json.dumps({"project_id": "demo-ch1", "jobs": ["demo-ch1"], "title": "Demo"}))
    monkeypatch.setattr(routes_demo, "DEMO_DIR", demo)

    settings.output_dir = tmp_path / "fresh"
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/demo").json() == {"available": True, "loaded": False, "project_id": "demo-ch1",
                                                  "jobs": ["demo-ch1"], "title": "Demo"}
        loaded = client.post("/api/demo").json()
        assert loaded["loaded"] is True
        job = client.get("/api/jobs/demo-ch1").json()
        assert job["status"] == "done" and job["result"]["outputs"]["rtl"]["pages"]
        assert client.get("/api/series/demo-ch1").json()["chapters"][0]["job_id"] == "demo-ch1"
        assert client.post("/api/demo").status_code == 200        # loading twice is harmless


def test_demo_unavailable(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(routes_demo, "DEMO_DIR", tmp_path / "missing")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/demo").json() == {"available": False}
        assert client.post("/api/demo").status_code == 404
