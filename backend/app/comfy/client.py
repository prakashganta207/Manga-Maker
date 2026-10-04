"""Thin HTTP client for a ComfyUI server.

Endpoints used:
  GET  /system_stats        is it alive? (+ GPU / VRAM info)
  GET  /object_info         every installed node type, with the model files it can load
  POST /upload/image        put a reference image into ComfyUI's input folder
  POST /prompt              queue a workflow -> prompt_id
  GET  /history/<id>        finished? which images were saved?
  GET  /view                download an image
  POST /free                unload models / free VRAM (important on an 8 GB GPU)
"""

from __future__ import annotations

import io
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from ..providers.base import ProviderError

IPADAPTER_NODES = {"IPAdapterUnifiedLoader", "IPAdapterAdvanced"}


@dataclass
class Capabilities:
    """What this ComfyUI install can actually do (from /object_info)."""

    nodes: set[str] = field(default_factory=set)
    checkpoints: list[str] = field(default_factory=list)
    ipadapter_models: list[str] = field(default_factory=list)
    clip_vision_models: list[str] = field(default_factory=list)
    ipadapter_presets: list[str] = field(default_factory=list)

    @property
    def has_ipadapter(self) -> bool:
        return IPADAPTER_NODES <= self.nodes and bool(self.ipadapter_models) and bool(self.clip_vision_models)

    def missing_nodes(self, needed: set[str]) -> set[str]:
        return needed - self.nodes

    def summary(self) -> dict[str, Any]:
        return {
            "node_count": len(self.nodes),
            "checkpoints": self.checkpoints,
            "ipadapter_nodes": sorted(IPADAPTER_NODES & self.nodes),
            "ipadapter_models": self.ipadapter_models,
            "clip_vision_models": self.clip_vision_models,
            "ipadapter_ready": self.has_ipadapter,
        }


def _choices(object_info: dict, node: str, field_name: str) -> list[str]:
    """Pull the list of allowed values for a node input (e.g. checkpoint file names)."""
    try:
        spec = object_info[node]["input"]["required"][field_name]
    except KeyError:
        try:
            spec = object_info[node]["input"]["optional"][field_name]
        except KeyError:
            return []
    if isinstance(spec, list) and spec and isinstance(spec[0], list):
        return [str(v) for v in spec[0]]
    # Newer ComfyUI: ["COMBO", {"options": [...]}]
    if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict):
        return [str(v) for v in spec[1].get("options", [])]
    return []


class ComfyClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 600,
                 poll_interval: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.http = client or httpx.Client(timeout=60)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.client_id = uuid.uuid4().hex
        self._caps: Capabilities | None = None

    # ------------------------------------------------------------------ low level
    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.http.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cannot reach ComfyUI at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"ComfyUI {method} {path} failed ({response.status_code}): {response.text[:400]}")
        return response

    def ping(self) -> dict[str, Any] | None:
        """System stats if reachable, else None (never raises)."""
        try:
            return self._call("GET", "/system_stats").json()
        except (ProviderError, ValueError):
            return None

    # ------------------------------------------------------------------ discovery
    def capabilities(self, refresh: bool = False) -> Capabilities:
        if self._caps is None or refresh:
            info = self._call("GET", "/object_info").json()
            self._caps = Capabilities(
                nodes=set(info.keys()),
                checkpoints=_choices(info, "CheckpointLoaderSimple", "ckpt_name"),
                ipadapter_models=_choices(info, "IPAdapterModelLoader", "ipadapter_file"),
                clip_vision_models=_choices(info, "CLIPVisionLoader", "clip_name"),
                ipadapter_presets=_choices(info, "IPAdapterUnifiedLoader", "preset"),
            )
        return self._caps

    def pick_checkpoint(self, preferred: str) -> str:
        """Use the configured checkpoint if installed, else the first anime-looking one."""
        names = self.capabilities().checkpoints
        if not names:
            raise ProviderError("ComfyUI has no checkpoints installed (models/checkpoints is empty)")
        if preferred in names:
            return preferred
        for name in names:
            if any(k in name.lower() for k in ("anim", "manga", "illustri", "pony")):
                return name
        return names[0]

    # ------------------------------------------------------------------ running
    def upload_image(self, path: Path) -> str:
        with open(path, "rb") as fh:
            info = self._call("POST", "/upload/image", files={"image": (path.name, fh, "image/png")},
                              data={"overwrite": "true"}).json()
        return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]

    def run(self, workflow: dict[str, Any]) -> Image.Image:
        """Queue a workflow, wait for it, return the first saved image."""
        missing = self.capabilities().missing_nodes(
            {n["class_type"] for n in workflow.values() if isinstance(n, dict)})
        if missing:
            raise ProviderError(f"ComfyUI is missing nodes: {sorted(missing)} (install the custom nodes)")
        body = self._call("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id}).json()
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ProviderError(f"ComfyUI rejected the workflow: {json.dumps(body)[:400]}")

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            entry = self._call("GET", f"/history/{prompt_id}").json().get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    messages = json.dumps(status.get("messages", []))[:600]
                    hint = " (out of VRAM: lower IMAGE_BASE_SIZE or start ComfyUI with --lowvram)" \
                        if "out of memory" in messages.lower() else ""
                    raise ProviderError(f"ComfyUI workflow failed: {messages}{hint}")
                for output in entry.get("outputs", {}).values():
                    for image in output.get("images", []):
                        data = self._call("GET", "/view", params={
                            "filename": image["filename"], "subfolder": image.get("subfolder", ""),
                            "type": image.get("type", "output")}).content
                        return Image.open(io.BytesIO(data)).convert("RGB")
                if status.get("completed"):
                    raise ProviderError("ComfyUI finished but produced no image (missing SaveImage node?)")
            time.sleep(self.poll_interval)
        raise ProviderError(f"ComfyUI timed out after {self.timeout}s")

    def free(self) -> None:
        """Ask ComfyUI to unload models and release VRAM (best effort)."""
        try:
            self._call("POST", "/free", json={"unload_models": True, "free_memory": True})
        except ProviderError:
            pass
