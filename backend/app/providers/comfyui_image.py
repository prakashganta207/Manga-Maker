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
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ..comfy.client import ComfyClient
from ..comfy.workflows import add_controlnet, add_loras, build_workflow
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
        if request.kind == "inpaint":
            return "inpaint_ipadapter" if refs and self.comfy.capabilities().has_ipadapter else "inpaint"
        if request.kind != "panel" or refs == 0:
            return "txt2img"
        if not self.comfy.capabilities().has_ipadapter:
            self._warn("IP-Adapter not installed in ComfyUI: panels use text prompts only (less consistent)")
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
            # Storyboard roughs only need the composition: far fewer steps.
            "steps": self.settings.storyboard_steps if request.kind == "storyboard" else self.settings.comfyui_steps,
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
        if name.startswith("inpaint"):
            if not (request.init_image and request.mask_image):
                raise ProviderError("Inpainting needs init_image and mask_image")
            # Uploaded fresh every time: the panel and the mask change between edits.
            values.update(init_image=self.comfy.upload_image(Path(request.init_image)),
                          mask_image=self.comfy.upload_image(Path(request.mask_image)),
                          denoise=round(max(0.05, min(1.0, request.denoise)), 3),
                          mask_grow=self.settings.inpaint_grow, mask_feather=self.settings.inpaint_feather)
        if name.startswith("ipadapter") or name == "inpaint_ipadapter":
            values["reference_image_1"] = self._upload(request.reference_images[0])
            if name == "ipadapter_2ref":
                values["reference_image_2"] = self._upload(request.reference_images[1])
        workflow = build_workflow(name, values, self.workflow_dir)
        if request.loras:
            installed = self.comfy.capabilities().loras
            usable = [(n, w) for n, w in request.loras if n in installed]
            if len(usable) < len(request.loras):
                self._warn("A character LoRA is not installed in ComfyUI's models/loras; drawing without it")
            if usable:
                workflow = add_loras(workflow, usable)
                name += "+lora"
        if request.control_image and request.kind == "panel":
            caps = self.comfy.capabilities()
            if caps.has_controlnet:
                model = (self.settings.controlnet_model if self.settings.controlnet_model in caps.controlnet_models
                         else caps.controlnet_models[0])
                workflow = add_controlnet(workflow, model=model, image=self.comfy.upload_image(Path(request.control_image)),
                                          control_type=request.control_type,
                                          strength=round(request.control_strength, 3), end=round(request.control_end, 3))
                name += "+controlnet"
            else:
                self._warn("ControlNet model or nodes missing in ComfyUI: storyboard layouts are not enforced")
        return name, workflow

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def supports_controlnet(self) -> bool:
        try:
            return self.comfy.capabilities().has_controlnet
        except ProviderError:
            return False

    def preprocess(self, image: Path, mode: str) -> Image.Image | None:
        """Pose skeleton (DWPose) or anime line art of a storyboard rough, via comfyui_controlnet_aux."""
        if not self.comfy.capabilities().can_preprocess(mode):
            self._warn(f"comfyui_controlnet_aux is missing the {mode} preprocessor (see SETUP_COMFYUI.md)")
            return None
        with Image.open(image) as img:
            resolution = max(256, min(1024, round(min(img.size) / 64) * 64))
        workflow = build_workflow(f"preprocess_{'pose' if mode == 'openpose' else 'lineart'}",
                                  {"image": self.comfy.upload_image(Path(image)), "resolution": resolution,
                                   "filename_prefix": f"manga_{mode}"}, self.workflow_dir)
        return self.comfy.run(workflow)

    def generate(self, request: ImageRequest) -> Image.Image:
        started = time.monotonic()
        name, workflow = self.build(request)
        fallback = None
        try:
            image = self.comfy.run(workflow)
        except ProviderError as exc:
            if "out of memory" not in str(exc).lower() and "out of vram" not in str(exc).lower():
                raise
            # 8 GB fallback: drop the heaviest extra (ControlNet), else draw at ~85% resolution.
            self.comfy.free()
            if request.control_image:
                fallback = "out of VRAM: retried without ControlNet"
                request = replace(request, control_image=None)
            else:
                fallback = "out of VRAM: retried at 85% resolution"
                request = replace(request, width=max(512, int(request.width * 0.85) // 64 * 64),
                                  height=max(512, int(request.height * 0.85) // 64 * 64))
            self._warn(f"Some images ran out of GPU memory ({fallback})")
            name, workflow = self.build(request)
            image = self.comfy.run(workflow)
        self.last_info = {"workflow": name, "seconds": round(time.monotonic() - started, 2),
                          "ipadapter": "ipadapter" in name, "controlnet": "controlnet" in name, "lora": "lora" in name}
        if fallback:
            self.last_info["fallback"] = fallback
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
