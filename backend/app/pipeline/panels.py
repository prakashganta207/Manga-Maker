"""Stage 3b — Generate one image per panel with the image provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from ..models import MangaScript
from ..providers.base import ImageProvider
from .characters import CharacterSheet
from .prompts import build_panel_request

PanelKey = tuple[int, int]  # (page_number, panel_number)


def panel_seed(job_seed: int, page_number: int, panel_number: int) -> int:
    # Different seed per panel (different compositions), but reproducible per story.
    return (job_seed + page_number * 1000 + panel_number) % (2**32)


def generate_panel_images(
    script: MangaScript,
    sheets: list[CharacterSheet],
    provider: ImageProvider,
    out_dir: Path,
    *,
    aspects: dict[PanelKey, float] | None = None,
    job_seed: int = 0,
    base_size: int = 832,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[PanelKey, Path]:
    """Draw every panel. Writes `panels/p01_03.png` files and `panels/prompts.json`.

    `aspects` maps a panel to its width/height ratio in the page layout, so the
    image is generated in the right shape (less cropping later).
    """
    panel_dir = out_dir / "panels"
    panel_dir.mkdir(parents=True, exist_ok=True)
    by_name = {s.name.lower(): s for s in sheets}
    aspects = aspects or {}
    all_panels = script.all_panels()
    results: dict[PanelKey, Path] = {}
    prompt_log = []

    for index, (page, panel) in enumerate(all_panels):
        key = (page.page_number, panel.panel_number)
        request = build_panel_request(
            panel, by_name, page_number=page.page_number, aspect=aspects.get(key, 1.0),
            seed=panel_seed(job_seed, *key), base_size=base_size, job_dir=out_dir,
        )
        image = provider.generate(request)
        path = panel_dir / f"p{key[0]:02d}_{key[1]:02d}.png"
        image.save(path)
        results[key] = path
        # Saved so you can see exactly what was sent to the image model.
        prompt_log.append({"page": key[0], "panel": key[1], "prompt": request.prompt,
                           "negative_prompt": request.negative_prompt, "seed": request.seed,
                           "width": request.width, "height": request.height})
        if on_progress:
            on_progress(index + 1, len(all_panels), f"page {key[0]} panel {key[1]}")

    (panel_dir / "prompts.json").write_text(json.dumps(prompt_log, indent=2), encoding="utf-8")
    return results
