"""Stage 4a — Page layout (plain code, no AI).

Places panel images into the Director's chosen layout template (margins, gutters, ink
borders), then hands each panel to the lettering engine for balloons, captions and SFX.

Reading order: right-to-left (RTL, manga — panel 1 is top-right) or left-to-right (LTR).
RTL pages are the template mirrored horizontally.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from ..agents.schemas import PlannedPage
from ..agents.state import PageLettering
from ..fonts import load_font, safe_text
from ..geometry import Rect
from . import templates
from .bubbles import render_lettering
from .lettering import letter_panel


@dataclass
class LayoutConfig:
    # A4 proportions at 150 dpi.
    width: int = 1240
    height: int = 1754
    margin: int = 64
    gutter: int = 22
    border: int = 5
    font_size: int = 26
    font_path: str = ""


def plan_page(template_id_or_count: str | int, cfg: LayoutConfig | None = None, rtl: bool = False) -> list[Rect]:
    """Panel rectangles in reading order for a template id (or the default template for a count)."""
    cfg = cfg or LayoutConfig()
    if isinstance(template_id_or_count, int):
        template = templates.best_template(["medium"] * template_id_or_count)
    else:
        template = templates.get(template_id_or_count)
    return templates.slot_rects(template, cfg.width, cfg.height, cfg.margin, cfg.gutter, rtl)


def panel_aspects(layout_ids: list[str], panel_counts: list[int],
                  cfg: LayoutConfig | None = None) -> dict[tuple[int, int], float]:
    """Width/height of every slot, so panel images are generated in the right shape."""
    aspects = {}
    for page_number, (layout_id, count) in enumerate(zip(layout_ids, panel_counts), start=1):
        for panel_number, rect in enumerate(plan_page(layout_id, cfg)[:count], start=1):
            aspects[(page_number, panel_number)] = rect.w / rect.h
    return aspects


def fit_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale and centre-crop to exactly width x height ("cover" fit), in greyscale."""
    return ImageOps.fit(image.convert("L"), (width, height), method=Image.Resampling.LANCZOS)


def compose_page(
    page: PlannedPage,
    layout_id: str,
    panel_images: dict[int, Image.Image | Path],
    cfg: LayoutConfig | None = None,
    *,
    rtl: bool = True,
    title: str | None = None,
    debug_keep_out: bool = False,
    lettering: "PageLettering | None" = None,
) -> tuple[Image.Image, dict]:
    """Build a finished page. Returns (image, info with panel and balloon boxes).

    With `lettering` (the stored, editable bubble layers) the text comes from there;
    without it, bubbles are planned on the fly (older callers, tests)."""
    cfg = cfg or LayoutConfig()
    canvas = Image.new("L", (cfg.width, cfg.height), 255)
    draw = ImageDraw.Draw(canvas)
    rects = plan_page(layout_id, cfg, rtl=rtl)
    if len(rects) != len(page.panels):
        raise ValueError(f"layout '{layout_id}' has {len(rects)} slots for {len(page.panels)} panels")
    info = {"page": page.page_number, "rtl": rtl, "layout": layout_id, "panels": []}

    for panel, rect in zip(page.panels, rects):
        source = panel_images.get(panel.panel_number)
        if source is not None:
            img = Image.open(source) if isinstance(source, (str, Path)) else source
            canvas.paste(fit_image(img, rect.w, rect.h), (rect.x, rect.y))
    inner = {panel.panel_number: rect.inset(cfg.border) for panel, rect in zip(page.panels, rects)}
    if lettering is not None:
        drawn = render_lettering(draw, lettering, inner, cfg.font_path)
        by_panel = {n: [b for b in drawn if b.meta["panel"] == n] for n in inner}
    for panel, rect in zip(page.panels, rects):
        if lettering is None:
            balloons = letter_panel(draw, panel, inner[panel.panel_number], font_size=cfg.font_size,
                                    font_path=cfg.font_path, rtl=rtl, debug_keep_out=debug_keep_out)
        else:
            balloons = by_panel[panel.panel_number]
        draw.rectangle(rect.box, outline=0, width=cfg.border)  # border last, crisp on top
        info["panels"].append({"panel": panel.panel_number, "rect": rect.to_dict(),
                               "balloons": [{"kind": b.kind, **b.box.to_dict()} for b in balloons]})

    small = load_font(max(12, cfg.font_size - 6), cfg.font_path)
    draw.text((cfg.width / 2, cfg.height - cfg.margin / 2), str(page.page_number), fill=0, font=small, anchor="mm")
    if title and page.page_number == 1:
        draw.text((cfg.width / 2, cfg.margin / 2), safe_text(title, cfg.font_path).upper(), fill=0,
                  font=load_font(cfg.font_size, cfg.font_path), anchor="mm")
    return canvas, info
