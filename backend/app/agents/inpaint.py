"""Inpainting a region of a panel ("paint a mask, say what should be there, redraw only that").

1. The mask (white = repaint) is drawn at the panel image's resolution (pipeline/masks.py).
2. The prompt = manga style + (the character's fixed bible tags, if the region shows a character)
   + what you typed.
3. If the region contains a character, IP-Adapter gets that character's reference image, so a
   repainted face or outfit still looks like them. "auto" picks the character whose detected face
   overlaps the mask (faces left to right = the panel's characters in order).
4. ComfyUI's inpaint workflow denoises only inside the mask and pastes the result back with a soft
   edge; the rest of the panel stays pixel-identical. The new drawing then goes through the normal
   quality loop (Editor review, redraws with fixes) as a new round.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ..pipeline.masks import bbox
from ..providers.base import ImageRequest
from ..vision.faces import detect_faces
from .graph import Ctx
from .prompt_builder import STYLE_PREFIX, STYLE_SUFFIX, choose_reference
from .redraw import DrawSettings, run_quality_loop
from .revision import find_panel
from .schemas import PlannedPanel
from .state import MangaProject, PanelResult


def region_character(project: MangaProject, planned: PlannedPanel, image: Path, mask: Image.Image) -> str | None:
    """The panel character whose detected face overlaps the mask (None if no face is under it)."""
    box = bbox(mask)
    if box is None or not planned.characters:
        return None
    faces = sorted(detect_faces(image), key=lambda f: f.x)
    for index, face in enumerate(faces):
        overlaps = not (face.x + face.w < box[0] or box[2] < face.x or face.y + face.h < box[1] or box[3] < face.y)
        if overlaps:
            return planned.characters[min(index, len(planned.characters) - 1)]
    return None


def inpaint_prompt(project: MangaProject, region: str, character: str | None) -> str:
    entry = project.character(character) if character else None
    parts = [STYLE_PREFIX]
    if entry:
        parts.append(f"({entry.tag_prompt()})")   # the fixed bible tags keep the character on-model
    parts += [region.strip().rstrip("."), STYLE_SUFFIX]
    return ", ".join(p for p in parts if p)


def inpaint_panel(project: MangaProject, ctx: Ctx, page: int, panel: int, mask_path: Path, region: str,
                  character: str = "auto", denoise: float | None = None) -> PanelResult:
    planned, directed, spec = find_panel(project, page, panel)
    result = project.panel_result(page, panel)
    if result is None or not result.image:
        raise ValueError("This panel has no image to inpaint yet")
    base = ctx.job_dir / result.image            # the panel as it is now (chosen attempt)
    mask = Image.open(mask_path).convert("L")
    who = region_character(project, planned, base, mask) if character == "auto" else (character or None)
    entry = project.character(who) if who else None
    reference = None
    if entry:
        ref, _ = choose_reference(entry, planned.emotion)
        reference = ctx.job_dir / ref if ref and (ctx.job_dir / ref).exists() else None
    ctx.progress("panels", 0.1, f"Inpainting '{region}'" + (f" with {entry.name}'s reference" if reference else ""))

    with Image.open(base) as img:
        size = img.size
    strength = ctx.settings.inpaint_denoise if denoise is None else denoise
    chosen = result.attempt(result.chosen_attempt)
    start = DrawSettings(prompt=inpaint_prompt(project, region, who), negative_prompt=spec.negative_prompt,
                         seed=(chosen.seed if chosen else spec.seed) + 7,
                         ipadapter_weight=(spec.ipadapter_weight or ctx.settings.ipadapter_weight) if reference else None,
                         notes=[f"inpaint: {region}" + (f" ({entry.name})" if entry else "")])

    def generate(draw: DrawSettings, attempt: int):
        image = ctx.image.generate(ImageRequest(
            prompt=draw.prompt, negative_prompt=draw.negative_prompt, width=size[0], height=size[1], seed=draw.seed,
            kind="inpaint", init_image=base, mask_image=mask_path, denoise=strength,
            reference_images=[reference] if reference else [],
            ipadapter_weight=draw.ipadapter_weight if reference else None,
            metadata={"page": page, "panel": panel, "region": region, "attempt": attempt}))
        info = dict(getattr(ctx.image, "last_info", {}) or {})
        info.setdefault("workflow", "inpaint")
        info.update(mask=mask_path.relative_to(ctx.job_dir).as_posix(), base=result.image, region=region,
                    character=who, denoise=strength)
        return image, info

    return run_quality_loop(project, ctx, spec, planned, directed, start=start, source="inpaint", generator=generate,
                            progress=lambda m: ctx.progress("panels", 0.5, m))


__all__ = ["inpaint_panel", "inpaint_prompt", "region_character"]
