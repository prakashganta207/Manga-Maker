"""Anthropic Claude LLM provider (story -> script).

Uses *structured outputs*: we send a JSON Schema in `output_config.format`, and the
API constrains Claude's answer so it is always valid JSON matching that schema
(right field names and types). The schema feature doesn't support some constraints
(string lengths, numeric ranges, array sizes), so we strip those before sending —
Pydantic still checks them afterwards, and the script stage asks Claude to fix
anything that fails ("repair loop").
"""

from __future__ import annotations

import copy
import json
from typing import Any

import anthropic

from ..config import Settings
from .base import LLMProvider, LLMResponse, ProviderError, TokenUsage

# Keywords the structured-output schema validator doesn't accept.
_UNSUPPORTED_KEYS = {
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems",
    "default",
}


def to_structured_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic JSON Schema acceptable for `output_config.format`.

    - removes unsupported constraint keywords (validated client-side by Pydantic instead)
    - sets `additionalProperties: false` on every object (required by the API)
    """
    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: clean(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
            if out.get("type") == "object" or "properties" in out:
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(copy.deepcopy(schema))


class AnthropicLLMProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings, client: Any | None = None):
        if client is None and not settings.anthropic_api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        # The SDK retries rate limits / server errors (2 retries by default).
        self.client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=300)
        self.model = settings.anthropic_model

    def build_request(self, *, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            # Structured output: the answer must be JSON matching this schema.
            # Effort "medium" is plenty for a short script (thinking stays adaptive).
            "output_config": {
                "effort": "medium",
                "format": {"type": "json_schema", "schema": to_structured_output_schema(schema)},
            },
            # If a safety classifier declines the request (rare false positive),
            # the API retries it on a suitable fallback model in the same call.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any],
                      task: str, context: dict[str, Any]) -> LLMResponse:
        try:
            response = self.client.beta.messages.create(**self.build_request(system=system, user=user, schema=schema))
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic rejected the API key (check ANTHROPIC_API_KEY)") from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Unknown Anthropic model '{self.model}' (check ANTHROPIC_MODEL)") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit reached; try again in a minute") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Could not reach the Anthropic API (network problem)") from exc

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(f"Claude declined to write this script (category: {category or 'unspecified'})")
        if response.stop_reason == "max_tokens":
            raise ProviderError("Claude's answer was cut off (max_tokens); try a shorter story")

        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if not text:
            raise ProviderError("Claude returned no text")
        usage = getattr(response, "usage", None)
        tokens = TokenUsage(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
        try:
            data: dict[str, Any] | str = json.loads(text)
        except json.JSONDecodeError:
            data = text  # the agent runner's repair loop will ask Claude to fix it
        return LLMResponse(data=data, usage=tokens, model=self.model)
