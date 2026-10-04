"""Stage 3a — Panel prompt builder.

Turns one panel of the script + the character sheets into a text-to-image prompt.

How diffusion prompts work (short version):
- The *positive* prompt lists what should be in the picture; words near the start
  tend to matter more, so we put framing and characters first, style last.
- The *negative* prompt lists what to steer away from (colour, photos, text...).
  We never ask the image model for text: speech bubbles are drawn later in code,
  because image models are bad at spelling.
- The *seed* fixes the starting noise, so the same prompt + seed = same image.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from ..models import Panel
from ..providers.base import ImageRequest

if TYPE_CHECKING:
    from .characters import CharacterSheet

STYLE_PROMPT = ("monochrome manga illustration, black and white, clean ink lines, "
                "screentone shading, high contrast, detailed linework")

NEGATIVE_PROMPT = ("color, colorful, photograph, photorealistic, 3d render, text, letters, words, "
                   "speech bubble, caption, watermark, signature, logo, blurry, lowres, "
                   "jpeg artifacts, extra fingers, deformed hands, extra limbs, duplicate person")

SHOT_PROMPTS = {
    "close-up": "close-up shot, face fills the frame, expressive eyes, emotional",
    "medium": "medium shot, characters shown from the waist up",
    "wide": "wide establishing shot, full body figures, detailed environment",
}

MOOD_PROMPTS = {
    "tense": "dramatic shadows, heavy black areas, tense atmosphere",
    "dramatic": "speed lines, dynamic angle, intense action",
    "melancholy": "soft rain-like screentone, quiet sad atmosphere",
    "cheerful": "bright clean whites, sparkles, light atmosphere",
    "calm": "soft lighting, peaceful atmosphere",
    "mysterious": "deep shadows, glowing light source, mysterious atmosphere",
}

_COUNT_WORDS = {1: "one person", 2: "two people", 3: "three people", 4: "four people"}


def mood_prompt(mood: str) -> str:
    return MOOD_PROMPTS.get(mood.lower().strip(), f"{mood} atmosphere")


def characters_prompt(names: Iterable[str], sheets: dict[str, "CharacterSheet"]) -> str:
    names = list(names)
    if not names:
        return "no people, scenery only"
    parts = []
    for name in names:
        sheet = sheets.get(name.lower())
        # Same description text in every panel = the basic trick for consistency.
        parts.append(f"({sheet.prompt_description})" if sheet else "(a person)")
    count = _COUNT_WORDS.get(len(names), f"{len(names)} people")
    # Left-to-right order matches where the lettering engine points bubble tails.
    position = " from left to right" if len(names) > 1 else ""
    return f"{count}{position}: " + ", ".join(parts)


def build_panel_prompt(panel: Panel, sheets: dict[str, "CharacterSheet"]) -> str:
    return ", ".join([
        SHOT_PROMPTS[panel.shot],
        characters_prompt(panel.characters, sheets),
        panel.action.rstrip("."),
        f"setting: {panel.setting}",
        mood_prompt(panel.mood),
        STYLE_PROMPT,
    ])


def image_size_for_aspect(aspect: float, base: int = 832, multiple: int = 64) -> tuple[int, int]:
    """Pick a width/height with the panel's aspect ratio and about base*base pixels.

    Diffusion models work in a latent space 8x smaller than the image, and most
    checkpoints behave best when sides are multiples of 64 and the total pixel count
    is close to what they were trained on (~1024² for SDXL, ~512² for SD 1.5).
    """
    aspect = max(0.25, min(4.0, aspect))
    area = base * base
    width = (area * aspect) ** 0.5
    height = width / aspect
    snap = lambda v: max(multiple, int(round(v / multiple)) * multiple)  # noqa: E731
    return snap(width), snap(height)


def build_panel_request(
    panel: Panel,
    sheets: dict[str, "CharacterSheet"],
    *,
    page_number: int,
    aspect: float = 1.0,
    seed: int = 0,
    base_size: int = 832,
    job_dir: Path | None = None,
) -> ImageRequest:
    width, height = image_size_for_aspect(aspect, base_size)
    refs = [sheets[n.lower()].reference_image for n in panel.characters
            if n.lower() in sheets and sheets[n.lower()].reference_image]
    return ImageRequest(
        prompt=build_panel_prompt(panel, sheets),
        negative_prompt=NEGATIVE_PROMPT,
        width=width,
        height=height,
        seed=seed,
        kind="panel",
        # Reference images for providers that can use them (IP-Adapter etc.).
        reference_images=[(job_dir / r) if job_dir else Path(r) for r in refs if r],
        metadata={"page": page_number, "panel": panel.panel_number, "shot": panel.shot,
                  "characters": list(panel.characters), "mood": panel.mood},
    )
