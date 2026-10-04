"""Helpers to adapt Pydantic JSON Schemas for different LLM APIs."""

from __future__ import annotations

import copy
from typing import Any

# Keywords that structured-output validators commonly reject. Pydantic still enforces them.
UNSUPPORTED_KEYS = {
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems",
    "default",
}


def strip_unsupported(schema: dict[str, Any], close_objects: bool = True) -> dict[str, Any]:
    """Drop unsupported keywords; optionally set additionalProperties: false on objects."""
    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: clean(v) for k, v in node.items() if k not in UNSUPPORTED_KEYS}
            if close_objects and (out.get("type") == "object" or "properties" in out):
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(copy.deepcopy(schema))


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace {"$ref": "#/$defs/X"} with the definition itself (some APIs don't follow refs)."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra})
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)
