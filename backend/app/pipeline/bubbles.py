"""Editable lettering layers: plan them once, store them in the job state, render pages from them.

    plan_lettering(...)   automatic placement (the Phase 1 planner; the Letterer agent in Phase 5)
    render_lettering(...) draws stored bubbles onto a page (used for every render, so your
                          edits in the canvas editor always win)

Positions are stored as fractions of each panel's inner rectangle (see `Bubble`).
"""

from __future__ import annotations

from PIL import ImageDraw

from ..agents.schemas import PlannedPage
from ..agents.state import Bubble, PageLettering
from PIL import Image

from ..agents.letterer import vertical_columns
from ..fonts import font_for, load_font, safe_text, sfx_font
from ..geometry import Rect
from .lettering import INK, MIN_FONT, PAPER, Balloon, draw_balloons, plan_balloons, tail_tip, wrap_text


def to_fraction(box: Rect, panel: Rect) -> tuple[float, float, float, float]:
    return ((box.x - panel.x) / panel.w, (box.y - panel.y) / panel.h, box.w / panel.w, box.h / panel.h)


def to_pixels(bubble: Bubble, panel: Rect) -> Rect:
    return Rect(round(panel.x + bubble.x * panel.w), round(panel.y + bubble.y * panel.h),
                max(8, round(bubble.w * panel.w)), max(8, round(bubble.h * panel.h)))


def plan_lettering(page: PlannedPage, inner_rects: list[Rect], *, font_size: int = 26, font_path: str = "",
                   rtl: bool = True) -> PageLettering:
    """Automatic placement for a whole page (in reading order)."""
    bubbles: list[Bubble] = []
    for panel, rect in zip(page.panels, inner_rects):
        for balloon in plan_balloons(panel, rect, font_size=font_size, font_path=font_path, rtl=rtl):
            x, y, w, h = to_fraction(balloon.box, rect)
            tail = None
            if balloon.tail_target:
                tip = tail_tip(balloon.box, balloon.tail_target, rect)   # store the real tip (editable)
                tail = ((tip[0] - rect.x) / rect.w, (tip[1] - rect.y) / rect.h)
            bubbles.append(Bubble(
                id=f"b{page.page_number}-{panel.panel_number}-{len(bubbles) + 1}", panel=panel.panel_number,
                kind=balloon.kind, text=balloon.meta.get("text") or " ".join(balloon.lines),
                speaker=balloon.meta.get("speaker"), x=x, y=y, w=w, h=h, tail=tail,
                font_size=balloon.font_size, order=len(bubbles)))
    return PageLettering(page=page.page_number, bubbles=bubbles)


def text_area(kind: str, box: Rect) -> tuple[int, int]:
    """Room for text inside a shape (an ellipse's inscribed box is ~70% of its size)."""
    if kind == "narration":
        return box.w - 24, box.h - 16
    if kind == "sfx":
        return box.w, box.h
    factor = 0.66 if kind in ("shout", "thought") else 0.72
    return int(box.w * factor), int(box.h * factor)


def fit_text(kind: str, text: str, box: Rect, size: int, font_path: str,
             draw: ImageDraw.ImageDraw) -> tuple[list[str], int]:
    """Auto-fit: wrap to the shape's width and shrink the font until the lines fit its height."""
    font_path = sfx_font() or font_path if kind == "sfx" else font_for(text, font_path)
    text = safe_text(text, font_path)
    width, height = text_area(kind, box)
    size = max(MIN_FONT, size)
    while True:
        font = load_font(size, font_path)
        if kind == "sfx":
            lines = [text]
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=max(3, size // 9))
            fits = right - left <= width and bottom - top <= height
        else:
            lines = wrap_text(text, font, max(20, width), draw)
            fits = len(lines) * int(size * 1.18) <= height and all(draw.textlength(l, font=font) <= width for l in lines)
        if fits or size <= (12 if kind == "sfx" else MIN_FONT - 4):
            return lines, size
        size -= 2


def fit_vertical(text: str, box: Rect, size: int) -> tuple[list[str], int]:
    """Vertical text: the largest size at which the columns (one per word, right to left) fit."""
    width, height = text_area("speech", box)
    size = max(MIN_FONT, size)
    while True:
        per_column = max(1, int(height / (size * 1.08)))
        columns = vertical_columns(text, per_column)
        if len(columns) * size * 1.25 <= width or size <= MIN_FONT - 4:
            return columns, size
        size -= 2


def draw_vertical(draw: ImageDraw.ImageDraw, box: Rect, columns: list[str], size: int, font_path: str) -> None:
    font = load_font(size, font_path)
    col_w = size * 1.25
    total = col_w * len(columns)
    x = box.x + box.w / 2 + total / 2 - col_w / 2           # first column on the right
    for column in columns:
        y = box.y + (box.h - len(column) * size * 1.08) / 2 + size / 2
        for ch in column:
            draw.text((x, y), ch, fill=INK, font=font, anchor="mm")
            y += size * 1.08
        x -= col_w


def draw_sfx(canvas: Image.Image, box: Rect, text: str, size: int, tilt: float) -> None:
    """Sound effect: heavy display letters, thick white outline, slightly rotated (drawn on a layer)."""
    font = load_font(size, sfx_font())
    stroke = max(4, size // 8)
    probe = ImageDraw.Draw(canvas)
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    w, h = right - left + 8, bottom - top + 8
    ink = Image.new("L", (w, h), PAPER)
    alpha = Image.new("L", (w, h), 0)
    ImageDraw.Draw(ink).text((4 - left, 4 - top), text, font=font, fill=INK, stroke_width=stroke, stroke_fill=PAPER)
    ImageDraw.Draw(alpha).text((4 - left, 4 - top), text, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    ink, alpha = ink.rotate(tilt, expand=True, fillcolor=PAPER), alpha.rotate(tilt, expand=True)
    x = round(box.x + (box.w - ink.width) / 2)
    y = round(box.y + (box.h - ink.height) / 2)
    canvas.paste(ink, (x, y), alpha)


def render_lettering(canvas: Image.Image, lettering: PageLettering, inner: dict[int, Rect],
                     font_path: str = "") -> list[Balloon]:
    """Draw the stored bubbles onto a page. `inner` maps panel number -> inner panel rect."""
    draw = ImageDraw.Draw(canvas)
    drawn = []
    for bubble in sorted(lettering.bubbles, key=lambda b: b.order):
        rect = inner.get(bubble.panel)
        if rect is None or not bubble.text.strip():
            continue
        box = to_pixels(bubble, rect)
        meta = {"id": bubble.id, "panel": bubble.panel}
        if bubble.kind == "sfx":
            lines, size = fit_text("sfx", bubble.text, box, bubble.font_size, font_path, draw)
            draw_sfx(canvas, box, lines[0], size, tilt=-7 if bubble.order % 2 else 6)
            drawn.append(Balloon("sfx", lines, size, box, meta=meta))
            continue
        tail = (rect.x + bubble.tail[0] * rect.w, rect.y + bubble.tail[1] * rect.h) if bubble.tail else None
        if bubble.vertical and bubble.kind != "narration":
            path = font_for(bubble.text, font_path)
            columns, size = fit_vertical(safe_text(bubble.text, path), box, bubble.font_size)
            balloon = Balloon(bubble.kind, [], size, box, tail_target=tail, meta=meta)
            draw_balloons(draw, [balloon], rect, path, exact_tails=True)   # the shape + tail
            draw_vertical(draw, box, columns, size, path)
        else:
            lines, size = fit_text(bubble.kind, bubble.text, box, bubble.font_size, font_path, draw)
            balloon = Balloon(bubble.kind, lines, size, box, tail_target=tail, meta=meta)
            draw_balloons(draw, [balloon], rect, font_for(bubble.text, font_path), exact_tails=True)
        drawn.append(balloon)
    return drawn
