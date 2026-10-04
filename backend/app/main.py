"""FastAPI app: submit a story, poll the job, download the results.

    POST /api/jobs            {"story": "..."}  -> job (status "queued")
    GET  /api/jobs/{id}       -> job with per-stage progress and, when done, the result
    GET  /api/jobs            -> recent jobs
    GET  /api/health          -> which providers are active (no secrets)
    GET  /files/{id}/...      -> generated files (PNG, PDF, JSON)

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

from .config import Settings
from .jobs import JobManager
from .pipeline.run import run_pipeline
from .providers import get_image_provider, get_llm_provider
from .providers.base import ImageProvider, LLMProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("manga")


class JobRequest(BaseModel):
    story: str = Field(min_length=20, max_length=20000, description="The short story to adapt")


def _with_urls(job: dict[str, Any]) -> dict[str, Any]:
    """Turn result file paths (relative to the job folder) into URLs under /files."""
    result = job.get("result")
    if not result:
        return job
    base = f"/files/{job['id']}/"
    url = lambda p: base + p if p else None  # noqa: E731
    result = dict(result)
    result["script_url"] = url(result.get("script"))
    result["prompts_url"] = url(result.get("prompts"))
    result["characters"] = [dict(c, reference_image_url=url(c.get("reference_image")))
                            for c in result.get("characters", [])]
    result["outputs"] = {
        direction: {"pages": [url(p) for p in out["pages"]], "pdf": url(out["pdf"])}
        for direction, out in result.get("outputs", {}).items()
    }
    return dict(job, result=result)


def create_app(settings: Settings | None = None, llm: LLMProvider | None = None,
               image: ImageProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    llm = llm or get_llm_provider(settings)
    image = image or get_image_provider(settings)
    log.info("Providers: llm=%s image=%s (%s)", llm.name, image.name, settings.describe())

    def runner(story: str, out_dir: Path, progress) -> dict[str, Any]:
        return run_pipeline(story, settings=settings, out_dir=out_dir, llm=llm, image=image, progress=progress)

    manager = JobManager(settings.output_dir, runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        manager.start()
        yield
        manager.stop()

    app = FastAPI(title="Story to Manga", version="0.1.0", lifespan=lifespan)
    app.state.manager = manager
    # Local dev tool: allow any origin (no cookies/credentials are used).
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "providers": {"llm": llm.name, "image": image.name},
                "panels_per_page": settings.panels_per_page, "max_pages": settings.max_pages}

    @app.post("/api/jobs", status_code=202)
    def create_job(request: JobRequest) -> dict[str, Any]:
        job = manager.submit(request.story.strip())
        return manager.snapshot(job.id)

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return manager.list()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = manager.snapshot(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _with_urls(job)

    app.mount("/files", StaticFiles(directory=settings.output_dir), name="files")
    return app


app = create_app()
