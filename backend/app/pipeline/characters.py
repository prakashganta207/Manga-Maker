"""Stage 2 — Character sheets.

Image models have no memory: every panel is drawn from scratch, so "Mira" can get a
different face in each panel. The cheapest fix is a *character sheet*: one fixed text
description per character, pasted word-for-word into every panel prompt, plus a
reference image. Stronger fixes (IP-Adapter with the reference image, or a LoRA
trained per character) are described in the README.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from ..models import CharacterSpec, MangaScript
from ..providers.base import ImageProvider, ImageRequest
from .prompts import NEGATIVE_PROMPT, STYLE_PROMPT


class CharacterSheet(BaseModel):
    name: str
    slug: str
    role: str
    hair: str
    outfit: str
    features: str
    # The exact phrase inserted into every panel prompt for this character.
    prompt_description: str
    # Fixed seed for this character's reference image (reproducible).
    seed: int
    reference_image: str | None = None  # path relative to the job folder


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "character"


def stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def describe(spec: CharacterSpec) -> str:
    # Names mean nothing to an image model — the visual description does the work.
    return f"{spec.hair}, wearing {spec.outfit}, {spec.features}"


def reference_prompt(sheet: CharacterSheet) -> str:
    return (f"character reference sheet, single character, full body, front view, standing, "
            f"plain white background, {sheet.prompt_description}, {STYLE_PROMPT}")


def build_character_sheets(
    script: MangaScript,
    image_provider: ImageProvider | None,
    out_dir: Path,
    on_progress: Callable[[int, int, str], None] | None = None,
    reference_size: int = 768,
) -> list[CharacterSheet]:
    """Create one sheet (+ reference image if a provider is given) per character.

    Writes `characters/<slug>.png` and `characters/sheets.json` under `out_dir`.
    """
    char_dir = out_dir / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    sheets: list[CharacterSheet] = []
    total = len(script.characters)

    for index, spec in enumerate(script.characters):
        sheet = CharacterSheet(
            name=spec.name, slug=slugify(spec.name), role=spec.role,
            hair=spec.hair, outfit=spec.outfit, features=spec.features,
            prompt_description=describe(spec), seed=stable_seed(spec.name),
        )
        if image_provider is not None:
            request = ImageRequest(
                prompt=reference_prompt(sheet),
                negative_prompt=NEGATIVE_PROMPT,
                width=reference_size, height=reference_size,
                seed=sheet.seed, kind="character_ref",
                metadata={"name": sheet.name,
                          "description_lines": [sheet.hair, sheet.outfit, sheet.features]},
            )
            image = image_provider.generate(request)
            path = char_dir / f"{sheet.slug}.png"
            image.save(path)
            sheet.reference_image = path.relative_to(out_dir).as_posix()
        sheets.append(sheet)
        if on_progress:
            on_progress(index + 1, total, sheet.name)

    (char_dir / "sheets.json").write_text(
        json.dumps([s.model_dump() for s in sheets], indent=2), encoding="utf-8")
    return sheets
