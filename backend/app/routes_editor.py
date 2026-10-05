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
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

from .agents.pipeline import ensure_lettering, export_documents, layout_config, manifest, render_pages
from .agents.cast_store import CastStore
from .agents.graph import Ctx
from .agents import history
from .agents.history import lettering_target, record, record_lettering
from .agents.inpaint import inpaint_panel
from .agents.revision import revise_panel
from .pipeline.masks import Stroke, coverage, rasterize, soften
from .agents.state import Bubble, MangaProject
from .pipeline.layout import plan_page

# One lock for all quick edits: they read-modify-write project.json.
EDIT_LOCK = threading.Lock()


class ReviseBody(BaseModel):
    instruction: str = Field(min_length=2, max_length=300, description='e.g. "make her angrier", "camera from below"')


class StrokeBody(BaseModel):
    points: list[float] = Field(min_length=2, max_length=20000, description="x0, y0, x1, y1... as slot fractions")
    size: float = Field(gt=0, le=1, description="brush diameter as a fraction of the slot width")
    erase: bool = False


class InpaintBody(BaseModel):
    strokes: list[StrokeBody] = Field(min_length=1, max_length=500)
    prompt: str = Field(min_length=2, max_length=300, description="What should be in the painted region")
    character: str = Field(default="auto", max_length=40, description='"auto", "" (nobody) or a character name')
    denoise: float | None = Field(default=None, ge=0.1, le=1.0)


class LockBody(BaseModel):
    locked: bool = True


class RestoreBody(BaseModel):
    version_id: int = Field(ge=1)


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

    def queue_panel_action(job_id: str, page: int, panel: int, label: str,
                           action: Callable[[MangaProject, Ctx], Any]) -> dict[str, Any]:
        """Run a slow panel action (GPU) on the single worker; progress shows in the job's `busy` text."""
        project = finished(job_id)
        page_or_404(project, page)
        if not any(s.page == page and s.panel == panel for s in project.prompts):
            raise HTTPException(404, f"No panel {panel} on page {page}")

        def task(job, _progress):
            directory = job_dir(job_id)
            fresh = MangaProject.load(directory)
            ctx = Ctx(settings=settings, llm=app.state.llm, image=app.state.image, job_dir=directory,
                      progress=lambda stage, fraction, message: manager.set_busy(job_id, f"{label} - {message}"))
            fresh.budget_limits(settings)
            try:
                action(fresh, ctx)
            finally:
                app.state.image.free_memory()
                fresh.save(directory)
            with EDIT_LOCK:
                refresh(job_id, fresh, [page])
            return manifest(fresh)

        manager.enqueue(job_id, task, label=label)
        return manager.snapshot(job_id)

    app.state.queue_panel_action = queue_panel_action

    @app.post("/api/jobs/{job_id}/panels/{page}/{panel}/revise", status_code=202)
    def revise(job_id: str, page: int, panel: int, body: ReviseBody) -> dict[str, Any]:
        """Panel instruction -> Panel Revision agent -> redraw through the Editor loop."""
        instruction = body.instruction.strip()
        return queue_panel_action(job_id, page, panel, f"Revising p{page}-{panel}: {instruction[:60]}",
                                  lambda project, ctx: revise_panel(project, ctx, page, panel, instruction))

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
            ensure_lettering(project, settings, job_dir(job_id))   # older projects: plan on the fly (saved on edit)
        lettering = project.page_lettering(page)
        return {
            "page": page, "direction": direction, "width": cfg.width, "height": cfg.height, "border": cfg.border,
            "layout": directed.layout, "panels": panels,
            "lettering": lettering.model_dump(mode="json") if lettering else None,
            "rendered": project.outputs.get(direction, {}).get("pages", [None] * page)[page - 1],
            "files_base": f"/files/{job_id}/",
        }

    @app.post("/api/jobs/{job_id}/panels/{page}/{panel}/inpaint", status_code=202)
    def inpaint(job_id: str, page: int, panel: int, body: InpaintBody) -> dict[str, Any]:
        """Repaint only the masked region of a panel (ComfyUI inpainting, Editor loop afterwards)."""
        project = finished(job_id)
        result = project.panel_result(page, panel)
        if result is None or not result.image:
            raise HTTPException(404, f"No drawn panel {panel} on page {page}")
        if body.character not in ("auto", "") and project.character(body.character) is None:
            raise HTTPException(422, f"No character named '{body.character}'")
        _, directed = page_or_404(project, page)
        slot = plan_page(directed.layout, layout_config(settings))[panel - 1]
        strokes = [Stroke(points=list(zip(s.points[0::2], s.points[1::2])), size=s.size, erase=s.erase)
                   for s in body.strokes]
        with Image.open(job_dir(job_id) / result.image) as img:
            mask = rasterize(strokes, img.size, (slot.w, slot.h))
        share = coverage(mask)
        if share < 0.002:
            raise HTTPException(422, "The mask is empty: paint over the region to change")
        if share > 0.9:
            raise HTTPException(422, "The mask covers almost the whole panel: use 'Tell the director' to redraw it instead")
        number = len(result.attempts) + 1
        mask_path = job_dir(job_id) / "panels" / f"p{page:02d}_{panel:02d}_mask{number}.png"
        soften(mask).save(mask_path)
        region = body.prompt.strip()
        return queue_panel_action(job_id, page, panel, f"Inpainting p{page}-{panel}: {region[:50]}",
                                  lambda proj, ctx: inpaint_panel(proj, ctx, page, panel, mask_path, region,
                                                                  body.character, body.denoise))

    # ------------------------------------------------------------------ versions, undo / redo, locks
    @app.get("/api/jobs/{job_id}/history")
    def get_history(job_id: str) -> dict[str, Any]:
        if manager.get(job_id) is None:
            raise HTTPException(404, "Job not found")
        return history.summary(app.state.load_project(job_id))

    def move(job_id: str, action: Callable[[MangaProject], Any]) -> dict[str, Any]:
        with EDIT_LOCK:
            project = finished(job_id)
            try:
                moved = action(project)
            except KeyError as exc:
                raise HTTPException(404, str(exc)) from exc
            if moved is None:
                raise HTTPException(409, "Nothing to do")
            change, page = moved
            refresh(job_id, project, [page])
            return {**history.summary(project), "applied": change.model_dump(), "page": page}

    @app.post("/api/jobs/{job_id}/history/undo")
    def undo(job_id: str) -> dict[str, Any]:
        return move(job_id, history.undo)

    @app.post("/api/jobs/{job_id}/history/redo")
    def redo(job_id: str) -> dict[str, Any]:
        return move(job_id, history.redo)

    @app.post("/api/jobs/{job_id}/history/restore")
    def restore(job_id: str, body: RestoreBody) -> dict[str, Any]:
        return move(job_id, lambda project: history.restore(project, body.version_id))

    @app.post("/api/jobs/{job_id}/panels/{page}/{panel}/lock")
    def lock_panel(job_id: str, page: int, panel: int, body: LockBody) -> dict[str, Any]:
        with EDIT_LOCK:
            project = finished(job_id)
            result = project.panel_result(page, panel)
            if result is None:
                raise HTTPException(404, f"No panel {panel} on page {page}")
            result.locked = body.locked
            project.save(job_dir(job_id))
            return {"page": page, "panel": panel, "locked": result.locked}

    @app.post("/api/jobs/{job_id}/characters/{name}/lock")
    def lock_character(job_id: str, name: str, body: LockBody) -> dict[str, Any]:
        """Lock a character's look: no tag edits / sheet regeneration, no automatic look changes."""
        with EDIT_LOCK:
            if manager.get(job_id) is None:
                raise HTTPException(404, "Job not found")
            project = app.state.load_project(job_id)
            character = project.character(name)
            if character is None:
                raise HTTPException(404, f"No character named '{name}'")
            character.look_locked = body.locked
            project.save(job_dir(job_id))
            if character.approved:
                CastStore(settings.output_dir).save(project, job_dir(job_id))  # later chapters inherit the lock
            return {"name": character.name, "look_locked": character.look_locked}

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
            lettering_baseline(project, page, project.page_lettering(page))
            project.lettering = [pl for pl in project.lettering if pl.page != page]
            refresh(job_id, project, [page])   # re-plans the page and records it as a new version
            return editor_page(job_id, page)


def lettering_baseline(project: MangaProject, page: int, before) -> None:
    """Old project without history: store the lettering as it was before this edit as the starting version."""
    if before is not None and (project.history is None or lettering_target(page) not in project.history.current):
        record(project, lettering_target(page), "auto_place", "Before your edits",
               {"bubbles": [b.model_dump(mode="json") for b in before.bubbles], "source": before.source},
               undoable=False)


def record_lettering_version(project: MangaProject, page: int, before, label: str) -> None:
    """Every saved bubble edit becomes a version (undo / redo / restore)."""
    lettering_baseline(project, page, before)
    record_lettering(project, page, "bubbles", label)
