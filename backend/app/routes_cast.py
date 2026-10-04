"""Cast approval endpoints (human-in-the-loop step before panels are drawn).

    POST  /api/jobs/{id}/characters/{name}/approve      {"approved": true}   approve / un-approve one
    POST  /api/jobs/{id}/approve                                             approve all + continue
    POST  /api/jobs/{id}/characters/{name}/regenerate   {"sheet": "turnaround"|"expressions"|"both"}
    PATCH /api/jobs/{id}/characters/{name}               edit description / visual tags

The job pauses with status "awaiting_approval" after the reference sheets. When every main
character is approved, the job is re-queued and resumes from project.json.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agents.cast_store import CastStore
from .agents.sheets import generate_sheets
from .agents.state import CharacterEntry, MangaProject


class ApproveRequest(BaseModel):
    approved: bool = True


class RegenerateRequest(BaseModel):
    sheet: Literal["turnaround", "expressions", "both"] = "both"


class TagsPatch(BaseModel):
    hair: str | None = Field(default=None, min_length=1, max_length=80)
    eyes: str | None = Field(default=None, min_length=1, max_length=60)
    outfit: str | None = Field(default=None, min_length=1, max_length=120)
    accessories: str | None = Field(default=None, max_length=80)
    distinguishing_marks: str | None = Field(default=None, max_length=80)


class CharacterPatch(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=400)
    personality: str | None = Field(default=None, min_length=1, max_length=200)
    age_range: str | None = Field(default=None, min_length=1, max_length=30)
    body_type: str | None = Field(default=None, min_length=1, max_length=60)
    visual_tags: TagsPatch | None = None


def new_seed(seed: int, version: int) -> int:
    # A different, still reproducible seed for each new version of the sheet.
    return (seed * 1103515245 + 12345 + version * 7919) % (2**32)


def register_cast_routes(app: FastAPI) -> None:
    manager = app.state.manager
    settings = app.state.settings

    def job_dir(job_id: str) -> Path:
        return app.state.job_dir(job_id)

    def editable(job_id: str) -> MangaProject:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if job.busy:
            raise HTTPException(409, f"Busy: {job.busy}. Try again in a moment.")
        if job.status != "awaiting_approval":
            raise HTTPException(409, f"The cast can only be changed while the job awaits approval (status: {job.status})")
        return app.state.load_project(job_id)

    def find(project: MangaProject, name: str) -> CharacterEntry:
        character = project.character(name)
        if character is None:
            raise HTTPException(404, f"No character named '{name}'")
        return character

    def resume_if_ready(job_id: str, project: MangaProject) -> None:
        if project.all_approved():
            CastStore(settings.output_dir).save(project, job_dir(job_id))
            manager.enqueue(job_id)  # resumes from project.json at the approval gate

    @app.post("/api/jobs/{job_id}/characters/{name}/approve")
    def approve_character(job_id: str, name: str, body: ApproveRequest) -> dict[str, Any]:
        project = editable(job_id)
        character = find(project, name)
        character.approved = body.approved
        character.status = "approved" if body.approved else "ready"
        project.save(job_dir(job_id))
        resume_if_ready(job_id, project)
        return project.model_dump(mode="json")

    @app.post("/api/jobs/{job_id}/approve")
    def approve_all(job_id: str) -> dict[str, Any]:
        project = editable(job_id)
        for character in project.characters:
            character.approved, character.status = True, "approved"
        project.save(job_dir(job_id))
        resume_if_ready(job_id, project)
        return manager.snapshot(job_id)

    @app.post("/api/jobs/{job_id}/characters/{name}/regenerate", status_code=202)
    def regenerate(job_id: str, name: str, body: RegenerateRequest) -> dict[str, Any]:
        project = editable(job_id)
        character = find(project, name)
        character.version += 1
        if body.sheet in ("turnaround", "both"):
            character.turnaround_seed = new_seed(character.turnaround_seed, character.version)
        if body.sheet in ("expressions", "both"):
            character.expression_seed = new_seed(character.expression_seed, character.version)
        character.approved, character.status = False, "generating"
        project.save(job_dir(job_id))

        def task(job, progress):
            # Runs on the single worker thread (one GPU job at a time).
            fresh = MangaProject.load(job_dir(job_id))
            entry = fresh.character(name)
            generate_sheets(entry, app.state.image, job_dir(job_id), which=body.sheet)
            app.state.image.free_memory()
            fresh.save(job_dir(job_id))
            return None

        manager.enqueue(job_id, task, label=f"regenerating {character.name}'s {body.sheet} sheet")
        return manager.snapshot(job_id)

    @app.patch("/api/jobs/{job_id}/characters/{name}")
    def edit_character(job_id: str, name: str, body: CharacterPatch) -> dict[str, Any]:
        project = editable(job_id)
        character = find(project, name)
        for field in ("description", "personality", "age_range", "body_type"):
            value = getattr(body, field)
            if value is not None:
                setattr(character, field, value.strip())
        if body.visual_tags:
            for field, value in body.visual_tags.model_dump(exclude_none=True).items():
                setattr(character.visual_tags, field, value.strip() or "none")
        # The look changed: the sheets no longer match until they are regenerated.
        character.approved, character.status = False, "edited"
        project.save(job_dir(job_id))
        return project.model_dump(mode="json")
