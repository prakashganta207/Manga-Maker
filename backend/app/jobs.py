"""A simple in-process job queue.

One background worker thread runs tasks one at a time (important: the GPU can only
draw one image at a time on 8 GB). A task is "run/resume the agent graph for job X" or
"regenerate a character sheet for job X". Job status lives in memory; the real state of
each job (the MangaProject) is on disk, so jobs can be resumed.

Statuses: queued -> running -> done | failed | awaiting_approval (paused for the cast).
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

from .agents.graph import STAGES

log = logging.getLogger("manga.jobs")

ProgressFn = Callable[[str, float, str], None]
# task(job, progress) -> result dict (must contain "status") or None
Task = Callable[["Job", ProgressFn], dict[str, Any] | None]


@dataclass
class StageState:
    name: str
    status: str = "pending"   # pending | running | done | waiting | failed
    progress: float = 0.0
    message: str = ""


@dataclass
class Job:
    id: str
    story: str
    options: dict[str, Any] = field(default_factory=dict)
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stages: dict[str, StageState] = field(default_factory=lambda: {s: StageState(s) for s in STAGES})
    error: str | None = None
    result: dict[str, Any] | None = None
    busy: str | None = None   # what the worker is doing right now (e.g. "regenerating Mira")

    @property
    def progress(self) -> float:
        return round(sum(s.progress for s in self.stages.values()) / len(self.stages), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "status": self.status, "progress": self.progress,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "stages": [vars(s).copy() for s in self.stages.values()],
            "error": self.error, "result": self.result, "options": self.options, "busy": self.busy,
        }


class JobManager:
    def __init__(self, output_dir: Path, runner: Task, max_jobs_kept: int = 200):
        self.output_dir = output_dir
        self.runner = runner
        self.max_jobs_kept = max_jobs_kept
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[tuple[str, Task | None, str] | None] = queue.Queue()
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
    def submit(self, story: str, options: dict[str, Any] | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], story=story, options=options or {})
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
        self._queue.put((job.id, None, "run"))
        return job

    def enqueue(self, job_id: str, task: Task | None = None, label: str = "resume") -> None:
        """Queue more work for an existing job (resume, or a custom task)."""
        with self._lock:
            job = self._jobs[job_id]
            if task is None:
                job.status, job.error = "queued", None
            job.busy = label if task is not None else None
            job.updated_at = time.time()
        self._queue.put((job_id, task, label))

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

    def register(self, job: Job) -> None:
        """Add a job object directly (used when reloading jobs from disk)."""
        with self._lock:
            self._jobs[job.id] = job

    # ---------------------------------------------------------------- internals
    def _trim(self) -> None:
        finished = [j for j in self._jobs.values() if j.status in ("done", "failed")]
        while len(self._jobs) > self.max_jobs_kept and finished:
            oldest = min(finished, key=lambda j: j.created_at)
            finished.remove(oldest)
            self._jobs.pop(oldest.id, None)

    def _update(self, job: Job, stage: str, fraction: float, message: str) -> None:
        if stage not in job.stages:
            return
        with self._lock:
            for name in STAGES[: STAGES.index(stage)]:
                earlier = job.stages[name]
                if earlier.status not in ("done",):
                    earlier.status, earlier.progress = "done", 1.0
            state = job.stages[stage]
            state.progress = max(0.0, min(1.0, fraction))
            state.status = "done" if fraction >= 1.0 else "running"
            state.message = message
            job.updated_at = time.time()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            job_id, task, label = item
            job = self.get(job_id)
            if job is None:
                continue
            is_run = task is None
            with self._lock:
                if is_run:
                    job.status = "running"
                job.busy = None if is_run else label
                job.updated_at = time.time()
            try:
                result = (task or self.runner)(job, lambda s, f, m, job=job: self._update(job, s, f, m))
                with self._lock:
                    if result is not None:
                        job.result = result
                    if is_run:
                        status = (result or {}).get("status", "done")
                        job.status = "awaiting_approval" if status == "awaiting_approval" else "done"
                        if job.status == "done":
                            for state in job.stages.values():
                                state.status, state.progress = "done", 1.0
                        else:
                            approval = job.stages["approval"]
                            approval.status, approval.message = "waiting", "Waiting for cast approval"
                    job.busy = None
                    job.updated_at = time.time()
            except Exception as exc:  # noqa: BLE001 — report any failure to the user
                log.exception("Job %s task %s failed", job.id, label)
                with self._lock:
                    message = f"{type(exc).__name__}: {exc}"
                    job.busy = None
                    job.updated_at = time.time()
                    if is_run:
                        for state in job.stages.values():
                            if state.status == "running":
                                state.status = "failed"
                        job.error = message
                        job.status = "failed"
                    else:
                        job.error = f"{label} failed: {message}"
