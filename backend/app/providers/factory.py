"""Pick provider implementations from settings.

LLM_PROVIDER:   auto (default) -> first configured of anthropic, gemini, openai-compatible,
                else mock | or force: mock, anthropic, gemini, openai
IMAGE_PROVIDER: auto (default) -> comfyui if it answers at COMFYUI_URL, else hosted if
                configured, else mock | or force: mock, comfyui, hosted
"""

from __future__ import annotations

import logging
from typing import Callable

import httpx

from ..config import Settings
from .base import ImageProvider, LLMProvider, ProviderError
from .mock_image import MockImageProvider
from .mock_llm import MockLLMProvider

log = logging.getLogger("manga.providers")


def resolve_llm_name(settings: Settings) -> str:
    choice = settings.llm_provider
    if choice != "auto":
        return choice
    if settings.anthropic_api_key:
        return "anthropic"
    if settings.gemini_api_key:
        return "gemini"
    if settings.openai_base_url and settings.openai_api_key:
        return "openai"
    return "mock"


def comfyui_reachable(url: str, timeout: float = 2.0) -> bool:
    if not url:
        return False
    try:
        return httpx.get(f"{url.rstrip('/')}/system_stats", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def resolve_image_name(settings: Settings, probe: Callable[[str], bool] = comfyui_reachable) -> str:
    choice = settings.image_provider
    if choice != "auto":
        return choice
    if settings.comfyui_url and probe(settings.comfyui_url):
        return "comfyui"
    if settings.hosted_image_api_url:
        return "hosted"
    return "mock"


def get_llm_provider(settings: Settings) -> LLMProvider:
    name = resolve_llm_name(settings)
    if name == "mock":
        return MockLLMProvider()
    # Real providers are imported lazily so mock mode needs none of their setup.
    if name == "anthropic":
        from .anthropic_llm import AnthropicLLMProvider
        return AnthropicLLMProvider(settings)
    if name == "gemini":
        from .gemini_llm import GeminiLLMProvider
        return GeminiLLMProvider(settings)
    if name == "openai":
        from .openai_compat_llm import OpenAICompatibleLLMProvider
        return OpenAICompatibleLLMProvider(settings)
    raise ProviderError(f"Unknown LLM_PROVIDER '{name}' (use auto, mock, anthropic, gemini or openai)")


def get_image_provider(settings: Settings) -> ImageProvider:
    name = resolve_image_name(settings)
    if name == "mock":
        if settings.image_provider == "auto":
            log.info("ComfyUI not reachable at %s -> using mock images", settings.comfyui_url or "(unset)")
        return MockImageProvider()
    if name == "comfyui":
        from .comfyui_image import ComfyUIImageProvider
        return ComfyUIImageProvider(settings)
    if name == "hosted":
        from .hosted_image import HostedImageProvider
        return HostedImageProvider(settings)
    raise ProviderError(f"Unknown IMAGE_PROVIDER '{name}' (use auto, mock, comfyui or hosted)")
