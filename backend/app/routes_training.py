"""Character LoRA training endpoints (Phase 5, optional).

    POST /api/jobs/{id}/characters/{name}/lora/train     start training (background, one at a time)
    GET  /api/jobs/{id}/trainings                         this job's trainings
    GET  /api/trainings/{training_id}                     status, progress, log tail
    POST /api/trainings/{training_id}/cancel
    POST /api/jobs/{id}/characters/{name}/lora/import     upload a LoRA trained elsewhere (CLOUD_TRAINING.md)
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .agents.cast_store import CastStore
from .agents.pipeline import manifest
from .agents.sheets import sheets_present
from .agents.state import MangaProject
from .training.lora import TrainingError, install_lora, kohya_available, resolve_trainer, trigger_word
from .training.manager import TrainingManager


def register_training_routes(app: FastAPI) -> None:
    manager = app.state.manager
    settings = app.state.settings

    def changed(job_id: str) -> None:
        job = manager.get(job_id)
        if job is not None:
            try:
                job.result = manifest(MangaProject.load(app.state.job_dir(job_id)))
            except Exception:  # noqa: BLE001
                pass
            job.updated_at = time.time()   # the UI polls this and refreshes the Cast page

    trainer = TrainingManager(settings, app.state.image, app.state.job_dir, on_change=changed)
    app.state.trainer = trainer

    def character_of(job_id: str, name: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        project = app.state.load_project(job_id)
        character = project.character(name)
        if character is None:
            raise HTTPException(404, f"No character named '{name}'")
        return job, project, character

    @app.get("/api/training/info")
    def training_info() -> dict[str, Any]:
        return {"trainer": resolve_trainer(settings), "kohya_available": kohya_available(settings),
                "steps": settings.lora_steps, "resolution": settings.lora_resolution, "rank": settings.lora_rank}

    @app.post("/api/jobs/{job_id}/characters/{name}/lora/train", status_code=202)
    def train(job_id: str, name: str) -> dict[str, Any]:
        job, project, character = character_of(job_id, name)
        if job.busy or job.status in ("queued", "running"):
            raise HTTPException(409, "The job is busy; train when it is idle")
        if not character.approved or not sheets_present(character, app.state.job_dir(job_id)):
            raise HTTPException(409, f"Approve {character.name}'s reference sheets before training a LoRA")
        try:
            return trainer.start(job_id, character.name).to_dict()
        except TrainingError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/jobs/{job_id}/trainings")
    def trainings(job_id: str) -> list[dict[str, Any]]:
        return trainer.list(job_id)

    @app.get("/api/trainings/{training_id}")
    def training(training_id: str) -> dict[str, Any]:
        item = trainer.get(training_id)
        if item is None:
            raise HTTPException(404, "Training not found")
        return item.to_dict()

    @app.post("/api/trainings/{training_id}/cancel")
    def cancel(training_id: str) -> dict[str, Any]:
        if trainer.get(training_id) is None:
            raise HTTPException(404, "Training not found")
        trainer.cancel(training_id)
        return trainer.get(training_id).to_dict()

    @app.post("/api/jobs/{job_id}/characters/{name}/lora/import")
    async def import_lora(job_id: str, name: str, file: UploadFile = File(...),
                          trigger: str = Form(default="")) -> dict[str, Any]:
        """Use a LoRA trained on a cloud GPU (CLOUD_TRAINING.md)."""
        _, project, character = character_of(job_id, name)
        if not (file.filename or "").endswith(".safetensors"):
            raise HTTPException(422, "Upload a .safetensors LoRA file")
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename)
        store = CastStore(settings.output_dir).root / project.project_id / "loras" / character.slug
        store.mkdir(parents=True, exist_ok=True)
        target = store / safe
        target.write_bytes(await file.read())
        installed = install_lora(settings, target)
        lora = character.lora
        lora.status, lora.trainer, lora.path = "ready", "imported", target.as_posix()
        lora.file, lora.trigger = installed or safe, (trigger.strip() or trigger_word(character))
        lora.error = None
        project.save(app.state.job_dir(job_id))
        if character.approved:
            CastStore(settings.output_dir).save(project, app.state.job_dir(job_id))
        changed(job_id)
        return {"name": character.name, "lora": lora.model_dump(),
                "installed_in_comfyui": installed is not None}
