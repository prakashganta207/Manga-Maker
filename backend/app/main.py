"""FastAPI app: submit a story, follow the agents, approve the cast, read the manga.

    POST /api/jobs                     {"story", "auto_approve"?, "project_id"?} -> job
    GET  /api/jobs                     recent jobs
    GET  /api/jobs/{id}                status, per-stage progress, result summary (URLs)
    GET  /api/jobs/{id}/project        the full agent state (beat sheet, plans, trace, cast...)
    GET  /api/layouts                  the page layout template library
    GET  /api/samples                  sample stories
    GET  /api/health                   active providers (no secrets)
    GET  /files/{id}/...               generated files
    (+ cast endpoints, see routes_cast in this file)

Run:  uvicorn app.main:app --reload --port 8000   (docs at /docs)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents.pipeline import manifest, new_project, run_project, templates_catalogue
from .agents.state import MangaProject
from .config import REPO_DIR, Settings
from .jobs import Job, JobManager
from .providers import get_image_provider, get_llm_provider
from .providers.base import ImageProvider, LLMProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("manga")

SAMPLES_DIR = REPO_DIR / "samples" / "stories"


class JobRequest(BaseModel):
    story: str = Field(min_length=20, max_length=20000, description="The short story to adapt")
    auto_approve: bool | None = Field(default=None, description="Skip the cast approval step")
    project_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
                                   description="Reuse the cast of an earlier project (a new chapter)")


def files_base(job_id: str) -> str:
    return f"/files/{job_id}/"


def with_urls(job: dict[str, Any]) -> dict[str, Any]:
    """Turn result file paths (relative to the job folder) into URLs under /files."""
    result = job.get("result")
    if not result:
        return job
    base = files_base(job["id"])
    url = lambda p: base + p if p else None  # noqa: E731
    result = dict(result)
    result["files_base"] = base
    result["project_url"] = url(result.get("project"))
    result["characters"] = [dict(c, reference_image_url=url(c.get("reference_image")))
                            for c in result.get("characters", [])]
    result["outputs"] = {d: {"pages": [url(p) for p in o.get("pages", [])], "pdf": url(o.get("pdf"))}
                         for d, o in result.get("outputs", {}).items()}
    return dict(job, result=result)


def create_app(settings: Settings | None = None, llm: LLMProvider | None = None,
               image: ImageProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    llm = llm or get_llm_provider(settings)
    image = image or get_image_provider(settings)
    log.info("Providers: llm=%s image=%s (%s)", llm.name, image.name, settings.describe())

    def job_dir(job_id: str) -> Path:
        return settings.output_dir / job_id

    def runner(job: Job, progress) -> dict[str, Any]:
        directory = job_dir(job.id)
        if MangaProject.exists(directory):
            project = MangaProject.load(directory)  # resume
        else:
            project = new_project(job.story, job.id, settings, project_id=job.options.get("project_id"),
                                  auto_approve=job.options.get("auto_approve"))
        project = run_project(project, settings=settings, job_dir=directory, llm=llm, image=image,
                              progress=progress, extras=app.state.extras_for(project))
        return manifest(project)

    manager = JobManager(settings.output_dir, runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        manager.start()
        yield
        manager.stop()

    app = FastAPI(title="Story to Manga", version="0.2.0", lifespan=lifespan)
    app.state.manager = manager
    app.state.settings = settings
    app.state.llm, app.state.image = llm, image
    app.state.extras_for = lambda project: {}
    # Local dev tool: allow any origin (no cookies/credentials are used).
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def load_project(job_id: str) -> MangaProject:
        if not MangaProject.exists(job_dir(job_id)):
            raise HTTPException(status_code=404, detail="No project state for this job yet")
        return MangaProject.load(job_dir(job_id))

    app.state.load_project = load_project
    app.state.job_dir = job_dir

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "providers": {"llm": llm.name, "llm_model": getattr(llm, "model", ""),
                                              "image": image.name},
                "max_pages": settings.max_pages, "auto_approve": settings.auto_approve}

    @app.post("/api/jobs", status_code=202)
    def create_job(request: JobRequest) -> dict[str, Any]:
        options = {k: v for k, v in {"auto_approve": request.auto_approve,
                                     "project_id": request.project_id}.items() if v is not None}
        job = manager.submit(request.story.strip(), options)
        return manager.snapshot(job.id)

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return manager.list()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = manager.snapshot(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return with_urls(job)

    @app.get("/api/jobs/{job_id}/project")
    def get_project(job_id: str) -> dict[str, Any]:
        if manager.get(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        data = load_project(job_id).model_dump(mode="json")
        data["files_base"] = files_base(job_id)
        return data

    @app.get("/api/layouts")
    def layouts() -> list[dict]:
        return templates_catalogue()

    @app.get("/api/samples")
    def samples() -> list[dict[str, str]]:
        if not SAMPLES_DIR.exists():
            return []
        return [{"id": p.stem, "title": p.stem.replace("_", " ").title(), "story": p.read_text(encoding="utf-8")}
                for p in sorted(SAMPLES_DIR.glob("*.txt"))]

    @app.get("/api/projects")
    def projects() -> list[dict]:
        return []  # filled in when the cast store exists

    from .routes_cast import register_cast_routes  # noqa: E402 — needs the objects above
    register_cast_routes(app)

    app.mount("/files", StaticFiles(directory=settings.output_dir), name="files")
    return app


app = create_app()
