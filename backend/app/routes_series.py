"""Series (projects with chapters) endpoints — Phase 5 series memory.

    GET   /api/series                       all series, newest first
    GET   /api/series/{project_id}          chapters, story so far, open threads, cast (+ LoRA status)
    PATCH /api/series/{project_id}          {"title"?, "style_tags"?}
    POST  /api/series/{project_id}/chapters {"story", "auto_approve"?} -> a new job (the next chapter)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agents.series import SeriesStore, series_summary


class SeriesPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    style_tags: str | None = Field(default=None, max_length=200,
                                   description='Extra art-style tags for every chapter, e.g. "heavy shadows, thick lines"')


class ChapterRequest(BaseModel):
    story: str = Field(min_length=20, max_length=20000)
    auto_approve: bool | None = None


def register_series_routes(app: FastAPI) -> None:
    manager = app.state.manager
    settings = app.state.settings
    store = SeriesStore(settings.output_dir)

    def get(project_id: str):
        series = store.load(project_id)
        if series is None:
            raise HTTPException(404, "No series with that id")
        return series

    def with_status(data: dict[str, Any]) -> dict[str, Any]:
        for chapter in data["chapters"]:
            job = manager.get(chapter["job_id"])
            if job is not None:
                chapter["status"] = job.status
        return data

    @app.get("/api/series")
    def list_series() -> list[dict[str, Any]]:
        return [with_status(series_summary(s, settings)) for s in store.list()]

    @app.get("/api/series/{project_id}")
    def one(project_id: str) -> dict[str, Any]:
        return with_status(series_summary(get(project_id), settings))

    @app.patch("/api/series/{project_id}")
    def patch(project_id: str, body: SeriesPatch) -> dict[str, Any]:
        series = get(project_id)
        if body.title is not None:
            series.title = body.title.strip()
        if body.style_tags is not None:
            series.style_tags = body.style_tags.strip()
        store.save(series)
        return with_status(series_summary(series, settings))

    @app.post("/api/series/{project_id}/chapters", status_code=202)
    def new_chapter(project_id: str, body: ChapterRequest) -> dict[str, Any]:
        get(project_id)
        options = {"project_id": project_id}
        if body.auto_approve is not None:
            options["auto_approve"] = body.auto_approve
        job = manager.submit(body.story.strip(), options)
        return manager.snapshot(job.id)
