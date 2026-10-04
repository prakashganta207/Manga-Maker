"""Character consistency score: how much does a panel "look like" the character's references?

CLIP is a model trained to map images (and text) to *embeddings*: lists of numbers where
similar-looking pictures end up close together. We embed the panel and each reference
image of a character (turnaround views + expressions) and take the cosine similarity —
1.0 = identical direction, ~0 = unrelated. The best match over the character's references
is the score. It's a rough signal (the panel also contains background, other people, a
different pose), but a sudden drop usually means the character drifted.

CLIP runs on the CPU here, so it never competes with ComfyUI for the 8 GB of VRAM.
If PyTorch/transformers aren't installed, a simple pixel-based fallback is used instead
(clearly labelled "simple" — it measures layout/tone similarity, not identity).
"""

from __future__ import annotations

import importlib.util
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

log = logging.getLogger("manga.consistency")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class Scorer:
    method = "none"

    def __init__(self, embed: Callable[[Image.Image], list[float]]):
        self._embed = embed
        self._cache: dict[str, list[float]] = {}

    def embedding(self, path: Path) -> list[float]:
        key = str(Path(path).resolve())
        if key not in self._cache:  # each reference image is embedded once
            with Image.open(path) as img:
                self._cache[key] = self._embed(img.convert("RGB"))
        return self._cache[key]

    def score(self, panel: Path, references: list[Path]) -> float | None:
        refs = [r for r in references if Path(r).exists()]
        if not refs:
            return None
        panel_vec = self.embedding(panel)
        return max(cosine(panel_vec, self.embedding(r)) for r in refs)


def simple_embed(image: Image.Image) -> list[float]:
    """Fallback 'embedding': a tiny greyscale thumbnail, mean-centred (no AI involved)."""
    thumb = ImageOps.fit(image.convert("L"), (32, 32))
    pixels = list(thumb.tobytes())  # one byte per pixel in "L" mode
    mean = sum(pixels) / len(pixels)
    return [p - mean for p in pixels]


class SimpleScorer(Scorer):
    method = "simple"

    def __init__(self):
        super().__init__(simple_embed)


class ClipScorer(Scorer):
    method = "clip"

    def __init__(self, model_name: str = "openai/clip-vit-base-patch32"):
        self.model_name = model_name
        super().__init__(self._clip_embed)

    @staticmethod
    @lru_cache(maxsize=2)
    def _load(model_name: str):
        import torch  # imported lazily: optional dependency
        from transformers import CLIPModel, CLIPProcessor

        torch.set_grad_enabled(False)
        model = CLIPModel.from_pretrained(model_name).eval()  # CPU
        processor = CLIPProcessor.from_pretrained(model_name)
        return model, processor

    def _clip_embed(self, image: Image.Image) -> list[float]:
        import torch

        model, processor = self._load(self.model_name)
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            features = model.get_image_features(**inputs)
        if not isinstance(features, torch.Tensor):  # some versions return an output object
            features = getattr(features, "image_embeds", None) or features.pooler_output
        return features[0].tolist()


def clip_available() -> bool:
    # find_spec checks the packages are installed without paying torch's import time.
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers"))


def get_scorer(kind: str, model_name: str) -> Scorer | None:
    """kind: auto (CLIP if installed, else simple) | clip | simple | off."""
    if kind == "off":
        return None
    if kind == "simple" or (kind == "auto" and not clip_available()):
        return SimpleScorer()
    try:
        scorer = ClipScorer(model_name)
        ClipScorer._load(model_name)  # load (and download on first use) right away to fail early
        return scorer
    except Exception as exc:  # noqa: BLE001 — never let scoring break a manga
        if kind == "clip":
            raise
        log.warning("CLIP unavailable (%s) -> using the simple scorer", exc)
        return SimpleScorer()
