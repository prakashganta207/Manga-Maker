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


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


@dataclass
class LLMResponse:
    """What an LLM call returns: the parsed JSON (or raw text if it wasn't JSON) + usage."""

    data: dict[str, Any] | str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""


class LLMProvider(ABC):
    """A text model that returns JSON matching a given JSON Schema."""

    name: str = "llm"
    model: str = ""

    @abstractmethod
    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        task: str,
        context: dict[str, Any],
    ) -> LLMResponse:
        """Return JSON that should match `schema` ("structured output").

        - `system` / `user`: the prompt text, used by real models.
        - `schema`: JSON Schema of the expected answer.
        - `task` + `context`: the raw inputs (e.g. the story). Real models ignore
          them; the mock uses them to build a fake answer without parsing prompts.

        The caller still validates the result with Pydantic — never trust it blindly.
        """


ImageKind = Literal["panel", "character_ref", "turnaround", "expressions"]


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
    # Character reference images. With IP-Adapter, the model "looks at" these while
    # drawing so the character keeps the same face/hair/outfit across panels.
    reference_images: list[Path] = field(default_factory=list)
    # How strongly references steer the image (None = provider default).
    ipadapter_weight: float | None = None
    # Structured info (shot, character names, ...) — used by the mock to draw
    # placeholders; real providers rely on the prompt text only.
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageProvider(ABC):
    """A text-to-image model."""

    name: str = "image"

    @abstractmethod
    def generate(self, request: ImageRequest) -> Image.Image:
        """Return a PIL image of roughly request.width x request.height."""

    def free_memory(self) -> None:
        """Release GPU memory between pipeline stages (no-op unless the provider has a GPU)."""

    def describe(self) -> dict[str, Any]:
        return {"name": self.name}
