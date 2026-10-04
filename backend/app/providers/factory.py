"""Pick provider implementations from settings.

LLM_PROVIDER / IMAGE_PROVIDER:
  auto (default) -> real provider if its key/URL is configured, otherwise mock
  mock           -> always mock
  anthropic | comfyui | hosted -> force that provider
"""

from __future__ import annotations

from ..config import Settings
from .base import ImageProvider, LLMProvider, ProviderError
from .mock_image import MockImageProvider
from .mock_llm import MockLLMProvider


def resolve_llm_name(settings: Settings) -> str:
    choice = settings.llm_provider
    if choice == "auto":
        return "anthropic" if settings.anthropic_api_key else "mock"
    return choice


def resolve_image_name(settings: Settings) -> str:
    choice = settings.image_provider
    if choice == "auto":
        if settings.comfyui_url:
            return "comfyui"
        if settings.hosted_image_api_url:
            return "hosted"
        return "mock"
    return choice


def get_llm_provider(settings: Settings) -> LLMProvider:
    name = resolve_llm_name(settings)
    if name == "mock":
        return MockLLMProvider()
    if name == "anthropic":
        # Imported lazily so mock mode works even without the SDK configured.
        from .anthropic_llm import AnthropicLLMProvider
        return AnthropicLLMProvider(settings)
    raise ProviderError(f"Unknown LLM_PROVIDER '{name}' (use auto, mock or anthropic)")


def get_image_provider(settings: Settings) -> ImageProvider:
    name = resolve_image_name(settings)
    if name == "mock":
        return MockImageProvider()
    if name == "comfyui":
        from .comfyui_image import ComfyUIImageProvider
        return ComfyUIImageProvider(settings)
    if name == "hosted":
        from .hosted_image import HostedImageProvider
        return HostedImageProvider(settings)
    raise ProviderError(f"Unknown IMAGE_PROVIDER '{name}' (use auto, mock, comfyui or hosted)")
