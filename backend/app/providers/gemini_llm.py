"""Google Gemini LLM provider (REST API, no extra SDK).

Structured output: `generationConfig.responseMimeType = application/json` plus a JSON
Schema in `responseJsonSchema` makes Gemini answer with JSON in that shape. If the API
rejects the schema (older models), we retry once with the schema written into the prompt.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings
from .base import ImageInput, LLMProvider, LLMResponse, ProviderError, TokenUsage, encode_image
from .schema_utils import inline_refs, strip_unsupported

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiLLMProvider(LLMProvider):
    name = "gemini"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.gemini_api_key:
            raise ProviderError("GEMINI_API_KEY is not set")
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.http = client or httpx.Client(timeout=300)

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            # Key goes in a header (never in the URL, so it can't leak into logs).
            return self.http.post(API.format(model=self.model), json=body,
                                  headers={"x-goog-api-key": self.api_key})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach the Gemini API: {exc}") from exc

    @staticmethod
    def image_parts(images: list[ImageInput] | None) -> list[dict[str, Any]]:
        """Vision input: each image as a labelled inline_data part (base64)."""
        parts: list[dict[str, Any]] = []
        for number, image in enumerate(images or [], start=1):
            media_type, data = encode_image(image.path)
            parts.append({"text": f"Image {number}: {image.label or image.path.name}"})
            parts.append({"inline_data": {"mime_type": media_type, "data": data}})
        return parts

    def generate_json(self, *, system: str, user: str, schema: dict[str, Any],
                      task: str, context: dict[str, Any], images: list[ImageInput] | None = None) -> LLMResponse:
        clean_schema = inline_refs(strip_unsupported(schema, close_objects=False))
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            # The question text is the LAST part (the fallback below rewrites it).
            "contents": [{"role": "user", "parts": [*self.image_parts(images), {"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": clean_schema},
        }
        response = self._post(body)
        if response.status_code == 400:
            # Fallback: plain JSON mode with the schema in the prompt.
            body["generationConfig"] = {"responseMimeType": "application/json"}
            body["contents"][0]["parts"][-1]["text"] = (
                f"{user}\n\nAnswer with JSON matching this JSON Schema:\n{json.dumps(clean_schema)}")
            response = self._post(body)
        if response.status_code in (401, 403):
            raise ProviderError("Gemini rejected the API key (check GEMINI_API_KEY)")
        if response.status_code == 429:
            raise ProviderError("Gemini rate limit reached; try again later")
        if response.status_code >= 400:
            raise ProviderError(f"Gemini API error {response.status_code}: {response.text[:300]}")

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = data.get("promptFeedback", {}).get("blockReason", "no candidates")
            raise ProviderError(f"Gemini returned no answer ({reason})")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        meta = data.get("usageMetadata", {})
        usage = TokenUsage(meta.get("promptTokenCount", 0), meta.get("candidatesTokenCount", 0))
        try:
            parsed: dict[str, Any] | str = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        return LLMResponse(parsed, usage, self.model)
