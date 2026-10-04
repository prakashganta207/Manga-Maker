"""Stage 4a — Page layout (plain code, no AI).

Arranges panel images into a page grid with margins, gutters and ink borders,
then hands each panel to the lettering engine for bubbles and captions.

Reading order: left-to-right (LTR, western comics) or right-to-left (RTL,
traditional manga). RTL is the LTR layout mirrored horizontally, so panel 1
sits top-right.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from ..fonts import load_font, safe_text
from ..geometry import Rect
from ..models import MangaScript, Page
from .lettering import letter_panel

# Row templates per panel count: (row height weight, [panel width weights]).
TEMPLATES: dict[int, list[tuple[float, list[float]]]] = {
    1: [(1.0, [1])],
    2: [(1.0, [1]), (1.0, [1])],
    3: [(1.0, [1]), (1.1, [1, 1])],
    4: [(0.9, [1]), (1.15, [1.2, 1]), (0.95, [1])],
    5: [(1.0, [1]), (1.0, [1, 1]), (1.0, [1, 1])],
    6: [(1.0, [1, 1]), (1.0, [1, 1]), (1.0, [1, 1])],
}


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


def plan_page(panel_count: int, cfg: LayoutConfig | None = None, rtl: bool = False) -> list[Rect]:
    """Return one Rect per panel, in reading order."""
    cfg = cfg or LayoutConfig()
    if panel_count not in TEMPLATES:
        raise ValueError(f"Layout supports 1-6 panels per page, got {panel_count}")
    rows = TEMPLATES[panel_count]
    inner_w = cfg.width - 2 * cfg.margin
    inner_h = cfg.height - 2 * cfg.margin
    usable_h = inner_h - cfg.gutter * (len(rows) - 1)
    total_weight = sum(weight for weight, _ in rows)

    rects: list[Rect] = []
    y = cfg.margin
    for row_index, (weight, cols) in enumerate(rows):
        row_h = round(usable_h * weight / total_weight)
        if row_index == len(rows) - 1:
            row_h = cfg.height - cfg.margin - y  # absorb rounding
        usable_w = inner_w - cfg.gutter * (len(cols) - 1)
        x = cfg.margin
        row_rects = []
        for col_index, col_weight in enumerate(cols):
            col_w = round(usable_w * col_weight / sum(cols))
            if col_index == len(cols) - 1:
                col_w = cfg.width - cfg.margin - x
            row_rects.append(Rect(x, y, col_w, row_h))
            x += col_w + cfg.gutter
        if rtl:
            # Mirror horizontally; reading order within the row becomes right-to-left.
            row_rects = [Rect(cfg.width - r.right, r.y, r.w, r.h) for r in row_rects]
        rects.extend(row_rects)
        y += row_h + cfg.gutter
    return rects


def panel_aspects(script: MangaScript, cfg: LayoutConfig | None = None) -> dict[tuple[int, int], float]:
    """Width/height ratio of every panel slot, so images can be generated in that shape."""
    aspects = {}
    for page in script.pages:
        for panel, rect in zip(page.panels, plan_page(len(page.panels), cfg)):
            aspects[(page.page_number, panel.panel_number)] = rect.w / rect.h
    return aspects


def fit_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale and centre-crop to exactly width x height ("cover" fit), in greyscale."""
    return ImageOps.fit(image.convert("L"), (width, height), method=Image.Resampling.LANCZOS)


def compose_page(
    page: Page,
    panel_images: dict[int, Image.Image | Path],
    cfg: LayoutConfig | None = None,
    *,
    rtl: bool = False,
    title: str | None = None,
    debug_keep_out: bool = False,
) -> tuple[Image.Image, dict]:
    """Build a finished page. Returns (image, info) where info has panel/bubble boxes."""
    cfg = cfg or LayoutConfig()
    canvas = Image.new("L", (cfg.width, cfg.height), 255)
    draw = ImageDraw.Draw(canvas)
    rects = plan_page(len(page.panels), cfg, rtl=rtl)
    info = {"page": page.page_number, "rtl": rtl, "panels": []}

    for panel, rect in zip(page.panels, rects):
        source = panel_images.get(panel.panel_number)
        if source is not None:
            img = Image.open(source) if isinstance(source, (str, Path)) else source
            canvas.paste(fit_image(img, rect.w, rect.h), (rect.x, rect.y))
        inner = rect.inset(cfg.border)
        balloons = letter_panel(draw, panel, inner, font_size=cfg.font_size,
                                font_path=cfg.font_path, rtl=rtl, debug_keep_out=debug_keep_out)
        # Border last so it stays crisp on top of the art.
        draw.rectangle(rect.box, outline=0, width=cfg.border)
        info["panels"].append({"panel": panel.panel_number, "rect": rect.to_dict(),
                               "balloons": [b.box.to_dict() for b in balloons]})

    # Page number in the bottom margin, title in the top margin of page 1.
    small = load_font(max(12, cfg.font_size - 6), cfg.font_path)
    draw.text((cfg.width / 2, cfg.height - cfg.margin / 2), str(page.page_number),
              fill=0, font=small, anchor="mm")
    if title and page.page_number == 1:
        draw.text((cfg.width / 2, cfg.margin / 2), safe_text(title, cfg.font_path).upper(), fill=0,
                  font=load_font(cfg.font_size, cfg.font_path), anchor="mm")
    return canvas, info
