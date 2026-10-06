"""Demo mode: load a pre-generated sample series instantly (no GPU, no API keys).

    GET  /api/demo   is a demo available? (and is it loaded?)
    POST /api/demo   copy samples/demo/ into the output folder, register its jobs, return where to go

samples/demo/ holds a finished 2-chapter series made with the real pipeline:
    jobs/<job_id>/...                  each chapter's job folder (project.json, panels, pages, exports)
    projects/<project_id>/...          the series memory, cast and LoRAs
    demo.json                          {"project_id": ..., "jobs": [...], "title": ...}
Everything is read-only from the demo's point of view: editing a demo chapter edits the copy.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

from fastapi import FastAPI, HTTPException

from .config import REPO_DIR

DEMO_DIR = REPO_DIR / "samples" / "demo"


def register_demo_routes(app: FastAPI) -> None:
    settings = app.state.settings
    manager = app.state.manager

    def info() -> dict[str, Any] | None:
        path = DEMO_DIR / "demo.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    @app.get("/api/demo")
    def demo_status() -> dict[str, Any]:
        data = info()
        if data is None:
            return {"available": False}
        loaded = all(manager.get(job) is not None for job in data["jobs"])
        return {"available": True, "loaded": loaded, **data}

    @app.post("/api/demo")
    def load_demo() -> dict[str, Any]:
        data = info()
        if data is None:
            raise HTTPException(404, "No demo project in samples/demo (run scripts/make_demo.py)")
        for job_id in data["jobs"]:
            target = settings.output_dir / job_id
            if not target.exists():
                shutil.copytree(DEMO_DIR / "jobs" / job_id, target)
        projects = DEMO_DIR / "projects"
        if projects.exists():
            for folder in projects.iterdir():
                target = settings.output_dir / "projects" / folder.name
                if not target.exists():
                    shutil.copytree(folder, target)
        app.state.reload_jobs()          # register the copied jobs (status "done")
        return {"available": True, "loaded": True, **data}
