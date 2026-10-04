"""ComfyUI image provider — talks to a ComfyUI server over its HTTP API.

ComfyUI runs Stable Diffusion-style models as a *workflow*: a graph of nodes
(load model -> encode prompt -> sample -> decode -> save). We send the graph as
JSON to `POST /prompt`, poll `GET /history/<id>` until it finishes, then download
the image from `GET /view`.

Diffusion parameters used here:
- checkpoint: the model file (e.g. an SDXL anime/manga checkpoint)
- steps: how many denoising steps (more = slower, usually cleaner; 20-30 is typical)
- cfg: "classifier-free guidance" — how strictly to follow the prompt
  (too low = ignores prompt, too high = harsh/over-cooked; 5-8 is typical)
- sampler/scheduler: the denoising algorithm; dpmpp_2m + karras is a solid default
- seed: starting noise; same seed + same settings = same image

Custom workflows: export your own graph from ComfyUI with "Save (API format)" and set
COMFYUI_WORKFLOW to that file. Put these placeholders in it and they get replaced:
"{{prompt}}", "{{negative_prompt}}", "{{seed}}", "{{width}}", "{{height}}",
"{{reference_image}}" (the first character reference image, uploaded for you —
use it with an IP-Adapter node for better character consistency).
"""

from __future__ import annotations

import copy
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ..config import Settings
from .base import ImageProvider, ImageRequest, ProviderError


def default_workflow(checkpoint: str, steps: int, cfg: float) -> dict[str, Any]:
    """A minimal text-to-image graph in ComfyUI's API format."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": "{{width}}", "height": "{{height}}", "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{negative_prompt}}", "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": "{{seed}}", "steps": steps, "cfg": cfg,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "manga", "images": ["8", 0]}},
    }


def fill_placeholders(node: Any, values: dict[str, Any]) -> Any:
    """Replace "{{name}}" strings anywhere in the workflow (keeps numbers as numbers)."""
    if isinstance(node, dict):
        return {k: fill_placeholders(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [fill_placeholders(v, values) for v in node]
    if isinstance(node, str):
        for key, value in values.items():
            token = "{{" + key + "}}"
            if node == token:
                return value
            if token in node:
                node = node.replace(token, str(value))
    return node


class ComfyUIImageProvider(ImageProvider):
    name = "comfyui"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, poll_interval: float = 1.0):
        if not settings.comfyui_url:
            raise ProviderError("COMFYUI_URL is not set")
        self.base_url = settings.comfyui_url.rstrip("/")
        self.timeout = settings.comfyui_timeout
        self.poll_interval = poll_interval
        self.client = client or httpx.Client(timeout=60)
        self.client_id = uuid.uuid4().hex
        workflow_path = getattr(settings, "comfyui_workflow", "")
        if workflow_path:
            try:
                self.workflow = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProviderError(f"Cannot read COMFYUI_WORKFLOW '{workflow_path}': {exc}") from exc
        else:
            self.workflow = default_workflow(settings.comfyui_checkpoint, settings.comfyui_steps, settings.comfyui_cfg)

    # ------------------------------------------------------------------ HTTP helpers
    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cannot reach ComfyUI at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"ComfyUI {method} {path} failed ({response.status_code}): {response.text[:300]}")
        return response

    def _upload(self, path: Path) -> str:
        with open(path, "rb") as fh:
            response = self._call("POST", "/upload/image",
                                  files={"image": (path.name, fh, "image/png")}, data={"overwrite": "true"})
        info = response.json()
        return f"{info.get('subfolder')}/{info['name']}" if info.get("subfolder") else info["name"]

    # ------------------------------------------------------------------ main
    def build_workflow(self, request: ImageRequest, reference_name: str = "") -> dict[str, Any]:
        values = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            # ComfyUI accepts large seeds, but keep it in a safe range.
            "seed": int(request.seed) % (2**32),
            "width": int(request.width),
            "height": int(request.height),
            "reference_image": reference_name,
        }
        return fill_placeholders(copy.deepcopy(self.workflow), values)

    def generate(self, request: ImageRequest) -> Image.Image:
        reference = ""
        if "{{reference_image}}" in json.dumps(self.workflow) and request.reference_images:
            reference = self._upload(Path(request.reference_images[0]))

        workflow = self.build_workflow(request, reference)
        prompt_id = self._call("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id}).json().get("prompt_id")
        if not prompt_id:
            raise ProviderError("ComfyUI did not return a prompt_id")

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            history = self._call("GET", f"/history/{prompt_id}").json()
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ProviderError(f"ComfyUI workflow failed: {json.dumps(status.get('messages', []))[:500]}")
                for output in entry.get("outputs", {}).values():
                    for image in output.get("images", []):
                        data = self._call("GET", "/view", params={
                            "filename": image["filename"], "subfolder": image.get("subfolder", ""),
                            "type": image.get("type", "output")}).content
                        return Image.open(io.BytesIO(data)).convert("RGB")
                if status.get("completed"):
                    raise ProviderError("ComfyUI finished but produced no image (is there a SaveImage node?)")
            time.sleep(self.poll_interval)
        raise ProviderError(f"ComfyUI timed out after {self.timeout}s")
