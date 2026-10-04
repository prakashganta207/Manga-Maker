"""Provider interfaces.

The pipeline never talks to an AI service directly. It talks to one of these two
small interfaces, and a factory picks the implementation (mock or real) from env
vars. That keeps the stages testable offline and makes it easy to swap vendors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a result (network, bad response, ...)."""


class LLMProvider(ABC):
    """A text model that returns JSON matching a given JSON Schema."""

    name: str = "llm"

    @abstractmethod
    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        task: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a JSON object (as a dict) that should match `schema`.

        - `system` / `user`: the prompt text, used by real models.
        - `schema`: JSON Schema of the expected answer ("structured output").
        - `task` + `context`: the raw inputs (e.g. the story). Real models ignore
          them; the mock uses them to build a fake answer without parsing prompts.

        The caller still validates the result with Pydantic — never trust it blindly.
        """


ImageKind = Literal["panel", "character_ref"]


@dataclass
class ImageRequest:
    """Everything an image model needs to draw one picture."""

    # Text-to-image prompts. "positive" = what we want; "negative" = what to avoid.
    prompt: str
    negative_prompt: str = ""
    width: int = 768
    height: int = 768
    # Diffusion models start from random noise; the seed fixes that noise so the
    # same prompt + seed gives the same picture (reproducible results).
    seed: int = 0
    kind: ImageKind = "panel"
    # Reference images of characters (for providers that support IP-Adapter etc.).
    reference_images: list[Path] = field(default_factory=list)
    # Structured info (shot, character names, ...) — used by the mock to label
    # placeholders; real providers rely on the prompt text only.
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageProvider(ABC):
    """A text-to-image model."""

    name: str = "image"

    @abstractmethod
    def generate(self, request: ImageRequest) -> Image.Image:
        """Return a PIL image of roughly request.width x request.height."""
