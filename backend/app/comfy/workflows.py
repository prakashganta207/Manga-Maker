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
