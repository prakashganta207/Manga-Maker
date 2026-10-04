"""ComfyUI image provider — runs our workflow templates on a ComfyUI server.

Diffusion parameters (set in .env, see SETUP_COMFYUI.md):
- checkpoint: the model file. An anime-style SDXL checkpoint draws manga best.
- steps: denoising steps (more = slower, usually cleaner; ~28 for SDXL anime models)
- cfg: "classifier-free guidance" — how strictly to follow the prompt (5–7 typical)
- sampler/scheduler: the denoising algorithm (euler_ancestral + normal suits anime models)
- seed: starting noise; same seed + same settings = same image

IP-Adapter: an add-on that turns a reference *image* into extra conditioning, so the
model draws "someone who looks like this picture". We feed it the character's
reference (turnaround view or matching expression) to keep faces/outfits consistent.

8 GB VRAM rules: one checkpoint at a time (every template loads the same one),
panels are generated one after another, and `free_memory()` unloads models between
pipeline stages.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ..comfy.client import ComfyClient
from ..comfy.workflows import build_workflow
from ..config import Settings
from .base import ImageProvider, ImageRequest, ProviderError


class ComfyUIImageProvider(ImageProvider):
    name = "comfyui"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, poll_interval: float = 1.0):
        if not settings.comfyui_url:
            raise ProviderError("COMFYUI_URL is not set")
        self.settings = settings
        self.comfy = ComfyClient(settings.comfyui_url, client=client, timeout=settings.comfyui_timeout,
                                 poll_interval=poll_interval)
        self.workflow_dir = Path(settings.comfyui_workflow_dir) if settings.comfyui_workflow_dir else None
        self._uploaded: dict[str, str] = {}
        self.warnings: list[str] = []
        # Info about the last generation (workflow used, time) — recorded in job state.
        self.last_info: dict[str, Any] = {}

    def choose_workflow(self, request: ImageRequest) -> str:
        refs = len(request.reference_images)
        if request.kind != "panel" or refs == 0:
            return "txt2img"
        if not self.comfy.capabilities().has_ipadapter:
            message = "IP-Adapter not installed in ComfyUI: panels use text prompts only (less consistent)"
            if message not in self.warnings:
                self.warnings.append(message)
            return "txt2img"
        return "ipadapter_1ref" if refs == 1 else "ipadapter_2ref"

    def _upload(self, path: Path) -> str:
        key = str(Path(path).resolve())
        if key not in self._uploaded:  # each reference is uploaded once per run
            self._uploaded[key] = self.comfy.upload_image(Path(path))
        return self._uploaded[key]

    def build(self, request: ImageRequest) -> tuple[str, dict[str, Any]]:
        name = self.choose_workflow(request)
        weight = request.ipadapter_weight if request.ipadapter_weight is not None else self.settings.ipadapter_weight
        values: dict[str, Any] = {
            "checkpoint": self.comfy.pick_checkpoint(self.settings.comfyui_checkpoint),
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "seed": int(request.seed) % (2**32),
            "width": int(request.width),
            "height": int(request.height),
            "steps": self.settings.comfyui_steps,
            "cfg": self.settings.comfyui_cfg,
            "sampler": self.settings.comfyui_sampler,
            "scheduler": self.settings.comfyui_scheduler,
            "filename_prefix": f"manga_{request.kind}",
            "ipadapter_preset": self.settings.ipadapter_preset,
            "ipadapter_weight": round(weight, 3),
            # Two references at once interfere with each other, so each gets less weight.
            "ipadapter_weight_2": round(weight * 0.65, 3),
            "ipadapter_end_at": self.settings.ipadapter_end_at,
        }
        if name.startswith("ipadapter"):
            values["reference_image_1"] = self._upload(request.reference_images[0])
            if name == "ipadapter_2ref":
                values["reference_image_2"] = self._upload(request.reference_images[1])
        return name, build_workflow(name, values, self.workflow_dir)

    def generate(self, request: ImageRequest) -> Image.Image:
        started = time.monotonic()
        name, workflow = self.build(request)
        image = self.comfy.run(workflow)
        self.last_info = {"workflow": name, "seconds": round(time.monotonic() - started, 2),
                          "ipadapter": name.startswith("ipadapter")}
        return image

    def free_memory(self) -> None:
        if self.settings.comfyui_free_vram:
            self.comfy.free()

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"name": self.name, "url": self.settings.comfyui_url}
        try:
            info.update(self.comfy.capabilities().summary())
        except ProviderError as exc:
            info["error"] = str(exc)
        return info
