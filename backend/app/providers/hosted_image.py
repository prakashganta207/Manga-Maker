"""Hosted image API provider — a STUB to adapt to the service you choose.

It already speaks a simple, generic JSON contract:

    POST HOSTED_IMAGE_API_URL
    Authorization: Bearer HOSTED_IMAGE_API_KEY
    {"prompt": "...", "negative_prompt": "...", "width": 832, "height": 1216, "seed": 123}

    -> {"image_base64": "<PNG/JPEG bytes, base64>"}     or
    -> {"image_url": "https://..."}

Most hosted APIs differ only in field names, so usually you only need to edit
`build_payload()` and `extract_image()` below. Remember: never print the API key.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import httpx
from PIL import Image

from ..config import Settings
from .base import ImageProvider, ImageRequest, ProviderError


class HostedImageProvider(ImageProvider):
    name = "hosted"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        if not settings.hosted_image_api_url:
            raise ProviderError("HOSTED_IMAGE_API_URL is not set")
        self.url = settings.hosted_image_api_url
        self.api_key = settings.hosted_image_api_key
        self.client = client or httpx.Client(timeout=300)

    def build_payload(self, request: ImageRequest) -> dict[str, Any]:
        # TODO: rename fields to match your provider's API.
        return {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "width": request.width,
            "height": request.height,
            "seed": request.seed,
        }

    def extract_image(self, body: dict[str, Any]) -> bytes:
        # TODO: adapt to your provider's response format.
        if "image_base64" in body:
            return base64.b64decode(body["image_base64"])
        if "image_url" in body:
            return self._post_or_get("GET", body["image_url"]).content
        raise ProviderError("Hosted image API response has no 'image_base64' or 'image_url'")

    def _post_or_get(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Cannot reach hosted image API: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"Hosted image API error {response.status_code}: {response.text[:300]}")
        return response

    def generate(self, request: ImageRequest) -> Image.Image:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self._post_or_get("POST", self.url, json=self.build_payload(request), headers=headers)
        return Image.open(io.BytesIO(self.extract_image(response.json()))).convert("RGB")
