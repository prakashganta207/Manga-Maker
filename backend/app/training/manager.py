"""Background LoRA training jobs (progress + logs), one at a time, sharing the GPU with the image worker.

The GPU can either draw panels or train, not both on 8 GB: both the job worker and the trainer hold
`GPU_LOCK` while they work, and training first asks ComfyUI to unload its models.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..agents.cast_store import CastStore
from ..agents.state import CharacterEntry, MangaProject
from ..config import Settings
from ..gpu import GPU_LOCK
from ..providers.base import ImageProvider, ImageRequest
from .lora import TrainingError, resolve_trainer, train_character_lora

log = logging.getLogger("manga.training")

EVAL_PROMPT = "monochrome, greyscale, manga, comic panel, medium shot, eye level, solo, ({tags}), standing, looking at viewer, simple background, ink lineart, screentone shading, masterpiece, best quality"
EVAL_SEEDS = (101, 202)


@dataclass
class Training:
    id: str
    job_id: str
    character: str
    trainer: str
    status: str = "queued"            # queued | running | done | failed | cancelled
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    log_path: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in vars(self).items() if k != "cancel"}
        data["log_tail"] = self.log_tail()
        return data

    def log_tail(self, lines: int = 25) -> list[str]:
        if not self.log_path or not Path(self.log_path).exists():
            return []
        text = Path(self.log_path).read_text(encoding="utf-8", errors="replace")
        # tqdm redraws its progress line with carriage returns; splitlines() splits on those too.
        rows = text.splitlines()
        return [r for r in rows if r.strip()][-lines:]


def evaluate(project: MangaProject, character: CharacterEntry, job_dir: Path, image: ImageProvider,
             settings: Settings, scorer, lora_file: str | None) -> dict[str, Any]:
    """Before/after check: the same test drawings without and with the LoRA, scored with CLIP
    against the character's references (higher = closer to the approved look)."""
    from ..agents.pipeline import character_references
    from ..agents.prompt_builder import choose_reference

    if lora_file and hasattr(image, "comfy"):
        image.comfy.capabilities(refresh=True)        # ComfyUI lists the newly installed LoRA
    refs = character_references(project, character.name, job_dir)
    ref, _ = choose_reference(character, "neutral")
    folder = job_dir / "characters" / character.slug / "lora_eval"
    folder.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"eval_images": {}}
    for label, use_lora in (("before", False), ("after", True)):
        scores, paths = [], []
        for seed in EVAL_SEEDS:
            prompt = EVAL_PROMPT.format(tags=(f"{character.lora.trigger}, " if use_lora else "") + character.tag_prompt())
            img = image.generate(ImageRequest(
                prompt=prompt, negative_prompt="color, text, watermark, lowres, bad hands", width=832, height=1216,
                seed=seed, kind="panel", reference_images=[job_dir / ref] if ref else [],
                ipadapter_weight=settings.ipadapter_weight_with_lora if use_lora else settings.ipadapter_weight,
                loras=[(lora_file, settings.lora_strength)] if use_lora and lora_file else []))
            path = folder / f"{label}_{seed}.png"
            img.save(path)
            paths.append(path.relative_to(job_dir).as_posix())
            score = scorer.score(path, refs) if scorer else None
            if score is not None:
                scores.append(score)
        results[label] = round(sum(scores) / len(scores), 3) if scores else None
        results["eval_images"][label] = paths
    image.free_memory()
    return results


class TrainingManager:
    def __init__(self, settings: Settings, image: ImageProvider, job_dir: Callable[[str], Path],
                 on_change: Callable[[str], None] | None = None):
        self.settings, self.image, self.job_dir = settings, image, job_dir
        self.on_change = on_change or (lambda job_id: None)
        self._items: dict[str, Training] = {}
        self._lock = threading.Lock()

    def get(self, training_id: str) -> Training | None:
        with self._lock:
            return self._items.get(training_id)

    def list(self, job_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = [t for t in self._items.values() if job_id is None or t.job_id == job_id]
        return [t.to_dict() for t in sorted(items, key=lambda t: t.created_at, reverse=True)]

    def active(self) -> Training | None:
        with self._lock:
            return next((t for t in self._items.values() if t.status in ("queued", "running")), None)

    def start(self, job_id: str, character: str) -> Training:
        if self.active():
            raise TrainingError("a LoRA is already training; wait for it to finish")
        training = Training(id=uuid.uuid4().hex[:10], job_id=job_id, character=character,
                            trainer=resolve_trainer(self.settings))
        with self._lock:
            self._items[training.id] = training
        self._update_character(job_id, character, status="queued", training_id=training.id, error=None)
        threading.Thread(target=self._run, args=(training,), name=f"lora-{training.id}", daemon=True).start()
        return training

    def cancel(self, training_id: str) -> None:
        training = self.get(training_id)
        if training:
            training.cancel = True

    # ------------------------------------------------------------------ internals
    def _update_character(self, job_id: str, name: str, **fields) -> MangaProject:
        directory = self.job_dir(job_id)
        project = MangaProject.load(directory)
        character = project.character(name)
        for key, value in fields.items():
            setattr(character.lora, key, value)
        project.save(directory)
        return project

    def _run(self, training: Training) -> None:
        from ..agents.pipeline import scorer_for

        def progress(fraction: float, message: str) -> None:
            training.progress, training.message = round(max(0.0, min(1.0, fraction)), 3), message

        with GPU_LOCK:   # no panel drawing while the GPU trains
            training.status = "running"
            self._update_character(training.job_id, training.character, status="training")
            directory = self.job_dir(training.job_id)
            try:
                self.image.free_memory()                       # ComfyUI unloads SDXL first
                project = MangaProject.load(directory)
                character = project.character(training.character)
                store = CastStore(self.settings.output_dir).root / project.project_id
                result = train_character_lora(project, character, directory, store, self.settings, progress,
                                              cancelled=lambda: training.cancel,
                                              on_log=lambda path: setattr(training, "log_path", str(path)))
                project = self._update_character(training.job_id, training.character, **result)
                character = project.character(training.character)
                progress(1.0, "comparing drawings without / with the LoRA")
                lora_file = result["file"] if result["trainer"] == "kohya" else None
                scores = evaluate(project, character, directory, self.image, self.settings,
                                  scorer_for(self.settings), lora_file)
                project = self._update_character(training.job_id, training.character, **scores)
                if character.approved:
                    CastStore(self.settings.output_dir).save(project, directory)  # later chapters reuse it
                training.status = "done"
                training.message = (f"done: consistency {scores.get('before')} -> {scores.get('after')}"
                                    if scores.get("before") is not None else "done")
            except Exception as exc:  # noqa: BLE001 — report every failure in the UI
                log.exception("LoRA training %s failed", training.id)
                training.status = "cancelled" if training.cancel else "failed"
                training.error = str(exc)
                self._update_character(training.job_id, training.character, status="failed", error=str(exc))
            finally:
                training.finished_at = time.time()
                self.on_change(training.job_id)
