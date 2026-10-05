"""Load ComfyUI workflow templates and inject parameters.

A ComfyUI "workflow" in API format is a dict of nodes: {node_id: {class_type, inputs}}.
Inputs are either literal values or links to another node's output: ["4", 0] means
"output #0 of node 4". Our templates put placeholders like "{{seed}}" where values go.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import BACKEND_DIR

WORKFLOW_DIR = BACKEND_DIR / "workflows"
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class WorkflowError(ValueError):
    pass


@lru_cache(maxsize=16)
def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_template(name: str, directory: Path | None = None) -> dict[str, Any]:
    path = (directory or WORKFLOW_DIR) / (name if name.endswith(".json") else f"{name}.json")
    if not path.exists():
        raise WorkflowError(f"Workflow template not found: {path}")
    return json.loads(_read(str(path)))


def inject(node: Any, values: dict[str, Any]) -> Any:
    """Replace placeholders everywhere. A string that is exactly "{{x}}" becomes the typed
    value (so numbers stay numbers); placeholders inside longer strings are substituted as text."""
    if isinstance(node, dict):
        return {k: inject(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [inject(v, values) for v in node]
    if isinstance(node, str):
        whole = _PLACEHOLDER.fullmatch(node)
        if whole and whole.group(1) in values:
            return values[whole.group(1)]
        return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), node)
    return node


def placeholders(node: Any) -> set[str]:
    """All placeholder names still present in a workflow."""
    text = json.dumps(node)
    return set(_PLACEHOLDER.findall(text))


def required_nodes(workflow: dict[str, Any]) -> set[str]:
    return {n["class_type"] for n in workflow.values() if isinstance(n, dict) and "class_type" in n}


def build_workflow(name: str, values: dict[str, Any], directory: Path | None = None) -> dict[str, Any]:
    """Load + inject + check nothing is left unfilled."""
    workflow = inject(copy.deepcopy(load_template(name, directory)), values)
    missing = placeholders(workflow)
    if missing:
        raise WorkflowError(f"Workflow '{name}' has unfilled placeholders: {sorted(missing)}")
    # "_meta" (node titles) is UI-only; ComfyUI ignores it, but strip to keep payloads small.
    for node in workflow.values():
        if isinstance(node, dict):
            node.pop("_meta", None)
    return workflow


# ControlNet node ids added by `add_controlnet` (high numbers so they never clash with templates).
CN_LOADER, CN_TYPE, CN_IMAGE, CN_APPLY = "60", "61", "62", "63"
UNION_TYPES = {"openpose": "openpose", "lineart": "canny/lineart/anime_lineart/mlsd", "depth": "depth"}


def add_controlnet(workflow: dict[str, Any], *, model: str, image: str, control_type: str, strength: float,
                   end: float, start: float = 0.0, sampler: str = "3") -> dict[str, Any]:
    """Insert ControlNet guidance into any workflow (txt2img or IP-Adapter).

    ControlNet is a copy of the diffusion model's encoder that takes an extra *control image*
    (a pose skeleton, line art or depth map) and nudges every denoising step so the picture follows
    its layout. It works on the conditioning: positive/negative prompts go in, "prompts + layout
    hints" come out, and the sampler uses those instead. The "union" model handles several control
    types, picked with SetUnionControlNetType.

    strength: how hard the layout is enforced (0.4-0.7 keeps it a guide, 1.0 copies it rigidly).
    end: stop guiding after this share of the steps, so the final details come from the prompt.
    """
    wf = copy.deepcopy(workflow)
    ksampler = wf[sampler]["inputs"]
    wf[CN_LOADER] = {"class_type": "ControlNetLoader", "inputs": {"control_net_name": model}}
    wf[CN_TYPE] = {"class_type": "SetUnionControlNetType",
                   "inputs": {"control_net": [CN_LOADER, 0], "type": UNION_TYPES.get(control_type, "auto")}}
    wf[CN_IMAGE] = {"class_type": "LoadImage", "inputs": {"image": image}}
    wf[CN_APPLY] = {"class_type": "ControlNetApplyAdvanced",
                    "inputs": {"positive": ksampler["positive"], "negative": ksampler["negative"],
                               "control_net": [CN_TYPE, 0], "image": [CN_IMAGE, 0], "strength": strength,
                               "start_percent": start, "end_percent": end}}
    ksampler["positive"], ksampler["negative"] = [CN_APPLY, 0], [CN_APPLY, 1]
    return wf


def add_loras(workflow: dict[str, Any], loras: list[tuple[str, float]], checkpoint: str = "4") -> dict[str, Any]:
    """Chain LoraLoader nodes after the checkpoint: every node that used the checkpoint's model or
    CLIP now uses the LoRA-patched versions. strength 0.8 = strong, but leaves room for the prompt."""
    if not loras:
        return workflow
    wf = copy.deepcopy(workflow)
    previous = checkpoint
    ids = []
    for index, (name, strength) in enumerate(loras):
        node_id = str(70 + index)
        wf[node_id] = {"class_type": "LoraLoader", "inputs": {"model": [previous, 0], "clip": [previous, 1],
                                                              "lora_name": name, "strength_model": strength,
                                                              "strength_clip": strength}}
        ids.append(node_id)
        previous = node_id
    for node_id, node in wf.items():
        if node_id in ids or not isinstance(node, dict):
            continue
        for key, value in node.get("inputs", {}).items():
            if isinstance(value, list) and len(value) == 2 and value[0] == checkpoint and value[1] in (0, 1):
                node["inputs"][key] = [previous, value[1]]      # model (0) and CLIP (1); the VAE (2) stays
    return wf
