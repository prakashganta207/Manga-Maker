"""Any OpenAI-compatible chat endpoint (OpenAI, Ollama, LM Studio, vLLM, OpenRouter, ...).

Structured output, the portable way: `response_format: {"type": "json_object"}` (JSON
mode, widely supported) + the JSON Schema in the system prompt. Pydantic validation
and the retry loop catch anything that doesn't match.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings
from .base import LLMProvider, LLMResponse, ProviderError, TokenUsage
from .schema_utils import inline_refs, strip_unsupported


class OpenAICompatibleLLMProvider(LLMProvider):
    name = "openai"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not (settings.openai_base_url and settings.openai_api_key):
            raise ProviderError("OPENAI_BASE_URL and OPENAI_API_KEY must both be set")
        self.base_url = settings.openai_base_url.rstrip("/")
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model
        self.http = client or httpx.Client(timeout=300)

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            return self.http.post(f"{self.base_url}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach {self.base_url}: {exc}") from exc

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any],
                      task: str, context: dict[str, Any]) -> LLMResponse:
        schema_text = json.dumps(inline_refs(strip_unsupported(schema, close_objects=False)))
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"{system}\n\nReply with a single JSON object matching this "
                                              f"JSON Schema:\n{schema_text}"},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        response = self._post(body)
        if response.status_code == 400 and "response_format" in response.text:
            body.pop("response_format")  # server doesn't support JSON mode; rely on the prompt
            response = self._post(body)
        if response.status_code in (401, 403):
            raise ProviderError("The OpenAI-compatible endpoint rejected the API key")
        if response.status_code == 429:
            raise ProviderError("Rate limit reached on the OpenAI-compatible endpoint")
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI-compatible API error {response.status_code}: {response.text[:300]}")

        data = response.json()
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError) as exc:
            raise ProviderError("Unexpected response from the OpenAI-compatible endpoint") from exc
        if choice.get("finish_reason") == "length":
            raise ProviderError("The model's answer was cut off (max tokens); try a shorter story")
        meta = data.get("usage") or {}
        usage = TokenUsage(meta.get("prompt_tokens", 0), meta.get("completion_tokens", 0))
        try:
            parsed: dict[str, Any] | str = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        return LLMResponse(parsed, usage, data.get("model") or self.model)
