"""A simple in-process job queue.

One background worker thread takes jobs from a queue and runs the pipeline.
Job state lives in memory (lost on restart); files stay in OUTPUT_DIR/<job_id>/.
Good enough for a single-user app; swap for Celery/RQ + Redis to scale out.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .pipeline.run import STAGES

log = logging.getLogger("manga.jobs")

# runner(story, out_dir, progress) -> manifest
Runner = Callable[[str, Path, Callable[[str, float, str], None]], dict[str, Any]]


@dataclass
class StageState:
    name: str
    status: str = "pending"   # pending | running | done | failed
    progress: float = 0.0
    message: str = ""


@dataclass
class Job:
    id: str
    story: str
    status: str = "queued"    # queued | running | done | failed
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stages: dict[str, StageState] = field(default_factory=lambda: {s: StageState(s) for s in STAGES})
    error: str | None = None
    result: dict[str, Any] | None = None

    @property
    def progress(self) -> float:
        return round(sum(s.progress for s in self.stages.values()) / len(self.stages), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stages": [vars(s).copy() for s in self.stages.values()],
            "error": self.error,
            "result": self.result,
        }


class JobManager:
    def __init__(self, output_dir: Path, runner: Runner, max_jobs_kept: int = 200):
        self.output_dir = output_dir
        self.runner = runner
        self.max_jobs_kept = max_jobs_kept
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker, name="manga-worker", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout)

    # ---------------------------------------------------------------- API
    def submit(self, story: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], story=story)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [{"id": j.id, "status": j.status, "progress": j.progress, "created_at": j.created_at,
                     "title": (j.result or {}).get("title")} for j in jobs]

    # ---------------------------------------------------------------- internals
    def _trim(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in ("done", "failed")]
        while len(self._jobs) > self.max_jobs_kept and finished:
            oldest = min(finished, key=lambda j: j.created_at)
            finished.remove(oldest)
            self._jobs.pop(oldest.id, None)

    def _update(self, job: Job, stage: str, fraction: float, message: str) -> None:
        with self._lock:
            # Any earlier stage still marked running is now finished.
            for name in STAGES[: STAGES.index(stage)]:
                earlier = job.stages[name]
                if earlier.status != "done":
                    earlier.status, earlier.progress = "done", 1.0
            state = job.stages[stage]
            state.progress = max(0.0, min(1.0, fraction))
            state.status = "done" if fraction >= 1.0 else "running"
            state.message = message
            job.updated_at = time.time()

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            job = self.get(job_id)
            if job is None:
                continue
            with self._lock:
                job.status = "running"
                job.updated_at = time.time()
            try:
                result = self.runner(job.story, self.output_dir / job.id,
                                     lambda s, f, m, job=job: self._update(job, s, f, m))
                with self._lock:
                    for state in job.stages.values():
                        state.status, state.progress = "done", 1.0
                    job.result = result
                    job.status = "done"
                    job.updated_at = time.time()
            except Exception as exc:  # noqa: BLE001 — report any failure to the user
                log.exception("Job %s failed", job.id)
                with self._lock:
                    for state in job.stages.values():
                        if state.status == "running":
                            state.status = "failed"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.status = "failed"
                    job.updated_at = time.time()
