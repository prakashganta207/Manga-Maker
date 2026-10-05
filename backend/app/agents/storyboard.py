"""Storyboard stage: a quick rough per panel -> a control image -> ControlNet guidance for the final.

Why: a full SDXL panel with IP-Adapter is slow (~35-50 s) and its composition is a lottery. A rough
at ~640 px with 12 steps takes a few seconds and already shows *where* things go. From that rough we
extract a **control image**:
  - **pose** (an OpenPose-format stick figure, estimated by DWPose): where each body, arm and head is;
  - **line art** (anime line extraction): the outlines of everything, used for scenery panels and
    whenever no pose is found (anime roughs sometimes don't read as human poses).
The final panel then runs with **ControlNet**, which nudges every denoising step to follow that
layout, at a configurable strength (CONTROLNET_STRENGTH) and only for the first part of the steps
(CONTROLNET_END), so details, faces and style still come from the prompt and IP-Adapter.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from ..config import Settings
from ..providers.base import ImageProvider, ImageRequest
from .graph import Ctx
from .prompt_builder import image_size_for_aspect
from .runner import AgentStep
from .schemas import PlannedPanel
from .state import MangaProject, PanelPrompt, StoryboardFrame


def storyboard_enabled(settings: Settings, image: ImageProvider) -> bool:
    if settings.storyboard == "off":
        return False
    return settings.storyboard == "on" or image.supports_controlnet()


def control_coverage(image: Image.Image) -> float:
    """Share of 'drawn' pixels in a control image (white lines/sticks on black, ControlNet's convention)."""
    grey = image.convert("L")
    histogram = grey.histogram()
    return sum(histogram[40:]) / max(1, grey.width * grey.height)


def control_modes(settings: Settings, planned: PlannedPanel) -> list[str]:
    if settings.storyboard_control in ("openpose", "lineart"):
        return [settings.storyboard_control]
    # Scenery has no body to pose; otherwise pose first, line art if no pose is found.
    return ["lineart"] if not planned.characters else ["openpose", "lineart"]


def storyboard_panel(p: MangaProject, ctx: Ctx, spec: PanelPrompt, planned: PlannedPanel) -> StoryboardFrame:
    folder = ctx.job_dir / "storyboard"
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    width, height = image_size_for_aspect(spec.width / spec.height, ctx.settings.storyboard_base_size)
    rough = ctx.image.generate(ImageRequest(prompt=spec.prompt, negative_prompt=spec.negative_prompt, width=width,
                                            height=height, seed=spec.seed, kind="storyboard",
                                            metadata={"page": spec.page, "panel": spec.panel,
                                                      "characters": list(planned.characters)}))
    rough_path = folder / f"p{spec.page:02d}_{spec.panel:02d}_rough.png"
    rough.save(rough_path)
    frame = StoryboardFrame(page=spec.page, panel=spec.panel, rough=rough_path.relative_to(ctx.job_dir).as_posix())
    tried = []
    for mode in control_modes(ctx.settings, planned):
        control = ctx.image.preprocess(rough_path, mode)
        tried.append(mode)
        if control is not None and control_coverage(control) >= (0.002 if mode == "openpose" else 0.01):
            path = folder / f"p{spec.page:02d}_{spec.panel:02d}_{mode}.png"
            control.save(path)
            frame.control, frame.control_type = path.relative_to(ctx.job_dir).as_posix(), mode
            break
    if frame.control is None:
        frame.note = f"no usable control image ({', '.join(tried)}): the panel is drawn without ControlNet"
    elif tried[0] != frame.control_type:
        frame.note = f"no pose found in the rough, using {frame.control_type}"
    frame.seconds = round(time.monotonic() - started, 2)
    p.budget.gpu_seconds = round(p.budget.gpu_seconds + frame.seconds, 2)
    p.budget.images += 1
    p.storyboards = [f for f in p.storyboards if (f.page, f.panel) != (spec.page, spec.panel)] + [frame]
    return frame


def node_storyboard(p: MangaProject, ctx: Ctx) -> None:
    """Pipeline node: one rough + control image per panel (skipped when ControlNet is unavailable)."""
    if not storyboard_enabled(ctx.settings, ctx.image):
        p.add_step(AgentStep(agent="storyboard", label="Storyboard", status="skipped",
                             notes=["ControlNet not available (or STORYBOARD=off): panels are drawn from the prompt only"]))
        return
    assert p.page_plan
    planned = {(pg.page_number, pn.panel_number): pn for pg, pn in p.page_plan.all_panels()}
    started, notes = time.monotonic(), []
    for index, spec in enumerate(p.prompts, start=1):
        if p.storyboard(spec.page, spec.panel):
            continue  # resumed job
        ctx.progress("storyboard", (index - 1) / len(p.prompts), f"Rough for page {spec.page} panel {spec.panel}")
        frame = storyboard_panel(p, ctx, spec, planned[(spec.page, spec.panel)])
        notes.append(f"p{spec.page}·{spec.panel}: {frame.control_type if frame.control else 'no control'} "
                     f"({frame.seconds:.1f}s){' - ' + frame.note if frame.note else ''}")
        p.save(ctx.job_dir)
    ctx.image.free_memory()
    p.add_step(AgentStep(agent="storyboard", label="Storyboard", status="ok", duration_s=round(time.monotonic() - started, 2),
                         notes=notes, inputs={"strength": ctx.settings.controlnet_strength,
                                              "end": ctx.settings.controlnet_end, "mode": ctx.settings.storyboard_control},
                         output={"frames": len(p.storyboards),
                                 "with_control": sum(1 for f in p.storyboards if f.control)}))


def storyboard_done(p: MangaProject) -> bool:
    return any(s.agent == "storyboard" for s in p.trace) and (
        all(p.storyboard(x.page, x.panel) for x in p.prompts)
        or any(s.agent == "storyboard" and s.status == "skipped" for s in p.trace))


def control_for(p: MangaProject, ctx: Ctx, page: int, panel: int) -> dict:
    """ImageRequest fields for ControlNet (empty when there's no usable control image)."""
    frame = p.storyboard(page, panel)
    if frame is None or frame.control is None or not storyboard_enabled(ctx.settings, ctx.image):
        return {}
    path = ctx.job_dir / frame.control
    if not path.exists():
        return {}
    return {"control_image": path, "control_type": frame.control_type,
            "control_strength": ctx.settings.controlnet_strength, "control_end": ctx.settings.controlnet_end}


__all__ = ["node_storyboard", "storyboard_panel", "storyboard_done", "control_for", "storyboard_enabled"]
