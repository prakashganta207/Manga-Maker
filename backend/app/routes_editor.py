"""Interactive editor endpoints (Phase 4, human in the loop).

    GET   /api/jobs/{id}/pages/{page}/editor?direction=rtl   page geometry, panel images, bubble layers
    PUT   /api/jobs/{id}/pages/{page}/lettering               save edited bubbles -> page + PDF re-rendered
    POST  /api/jobs/{id}/pages/{page}/lettering/reset         back to automatic placement

Edits are only allowed when the job is finished and the worker isn't busy with it. Quick
edits (bubbles) run in the request; slow ones (redraws, inpainting) are queued on the single
GPU worker and report progress through the normal job status API.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agents.pipeline import ensure_lettering, export_documents, layout_config, manifest, render_pages
from .agents.state import Bubble, MangaProject
from .pipeline.layout import plan_page

# One lock for all quick edits: they read-modify-write project.json.
EDIT_LOCK = threading.Lock()


class LetteringBody(BaseModel):
    bubbles: list[Bubble] = Field(max_length=80)
    label: str = Field(default="Edited lettering", max_length=80)


def register_editor_routes(app: FastAPI) -> None:
    manager = app.state.manager
    settings = app.state.settings

    def job_dir(job_id: str) -> Path:
        return app.state.job_dir(job_id)

    def finished(job_id: str) -> MangaProject:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if job.busy:
            raise HTTPException(409, f"Busy: {job.busy}. Try again when it finishes.")
        if job.status != "done":
            raise HTTPException(409, f"The editor opens when the manga is finished (status: {job.status})")
        return app.state.load_project(job_id)

    def page_or_404(project: MangaProject, page: int):
        if not project.page_plan or not 1 <= page <= len(project.page_plan.pages):
            raise HTTPException(404, f"No page {page}")
        return project.page_plan.pages[page - 1], project.director.pages[page - 1]

    def refresh(job_id: str, project: MangaProject, pages: list[int] | None = None) -> None:
        """Re-render pages + PDFs, save, and update the job's result summary."""
        render_pages(project, settings, job_dir(job_id), pages)
        export_documents(project, job_dir(job_id))
        project.save(job_dir(job_id))
        job = manager.get(job_id)
        if job is not None:
            job.result = manifest(project)

    app.state.refresh_pages = refresh

    @app.get("/api/jobs/{job_id}/pages/{page}/editor")
    def editor_page(job_id: str, page: int, direction: Literal["rtl", "ltr"] = "rtl") -> dict[str, Any]:
        if manager.get(job_id) is None:
            raise HTTPException(404, "Job not found")
        project = app.state.load_project(job_id)
        planned, directed = page_or_404(project, page)
        cfg = layout_config(settings)
        rects = plan_page(directed.layout, cfg, rtl=(direction == "rtl"))
        panels = []
        for panel, rect in zip(planned.panels, rects):
            result = project.panel_result(page, panel.panel_number)
            panels.append({
                "panel": panel.panel_number, "rect": rect.to_dict(), "inner": rect.inset(cfg.border).to_dict(),
                "image": result.image if result else None, "status": result.status if result else None,
                "characters": panel.characters, "action": panel.action, "emotion": panel.emotion,
                "dialogue": [d.model_dump() for d in panel.dialogue], "narration": panel.narration, "sfx": panel.sfx,
            })
        if project.page_lettering(page) is None:
            ensure_lettering(project, settings)   # older projects: plan the layers on the fly (saved on edit)
        lettering = project.page_lettering(page)
        return {
            "page": page, "direction": direction, "width": cfg.width, "height": cfg.height, "border": cfg.border,
            "layout": directed.layout, "panels": panels,
            "lettering": lettering.model_dump(mode="json") if lettering else None,
            "rendered": project.outputs.get(direction, {}).get("pages", [None] * page)[page - 1],
            "files_base": f"/files/{job_id}/",
        }

    @app.put("/api/jobs/{job_id}/pages/{page}/lettering")
    def save_lettering(job_id: str, page: int, body: LetteringBody) -> dict[str, Any]:
        with EDIT_LOCK:
            project = finished(job_id)
            planned, _ = page_or_404(project, page)
            numbers = {p.panel_number for p in planned.panels}
            bad = sorted({b.panel for b in body.bubbles} - numbers)
            if bad:
                raise HTTPException(422, f"Bubbles point at panels that don't exist on page {page}: {bad}")
            ids = [b.id for b in body.bubbles]
            if len(set(ids)) != len(ids):
                raise HTTPException(422, "Bubble ids must be unique")
            current = project.page_lettering(page)
            before = current.model_copy(deep=True) if current else None
            if current is None:
                from .agents.state import PageLettering
                current = PageLettering(page=page)
                project.lettering.append(current)
            current.bubbles = [b.model_copy() for b in body.bubbles]
            current.source = "edited"
            record_lettering_version(project, page, before, body.label)
            refresh(job_id, project, [page])
            return editor_page(job_id, page)

    @app.post("/api/jobs/{job_id}/pages/{page}/lettering/reset")
    def reset_lettering(job_id: str, page: int) -> dict[str, Any]:
        with EDIT_LOCK:
            project = finished(job_id)
            page_or_404(project, page)
            before = project.page_lettering(page)
            project.lettering = [pl for pl in project.lettering if pl.page != page]
            render_pages(project, settings, job_dir(job_id), [page])   # re-plans the missing page
            record_lettering_version(project, page, before, "Automatic placement")
            refresh(job_id, project, [page])
            return editor_page(job_id, page)


def record_lettering_version(project: MangaProject, page: int, before, label: str) -> None:
    """Hook for version history (M7)."""
