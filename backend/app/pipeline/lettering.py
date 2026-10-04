"""Stage 4b — Lettering: speech bubbles and narration boxes, drawn with Pillow.

Why not let the image model draw the text? Diffusion models can't spell reliably,
so all text is drawn here in code, where it's always correct and editable.

Placement rules:
- Never cover the panel's centre (the "keep-out" zone), where the action usually is.
- Follow reading order: first balloon starts at the top corner where reading begins
  (top-left for LTR, top-right for RTL), next ones follow along the top, then the
  sides, then the bottom.
- Balloons don't overlap each other; if nothing fits, the font shrinks.
- Speech tails point toward the speaker's position in the panel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PIL import ImageDraw

from ..fonts import load_font, safe_text
from ..geometry import Rect, character_x_fraction
from ..models import Panel

INK = 0
PAPER = 255
LINE_W = 3
EDGE_PAD = 10        # distance from panel border
BALLOON_GAP = 8      # min gap between balloons
MIN_FONT = 14


@dataclass
class Balloon:
    kind: str                      # "speech" | "shout" | "narration"
    lines: list[str]
    font_size: int
    box: Rect                      # outer bounding box of the shape (tail not included)
    tail_target: tuple[float, float] | None = None
    overflow: bool = False         # True if it had to be forced into a bad spot
    meta: dict = field(default_factory=dict)


def keep_out_zone(rect: Rect) -> Rect:
    """The middle of the panel (50% wide x 40% tall) stays free of text."""
    return Rect(rect.x + rect.w // 4, rect.y + int(rect.h * 0.30), rect.w // 2, int(rect.h * 0.40))


# --------------------------------------------------------------------------- text
def wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        # Break words that are longer than a whole line.
        while draw.textlength(word, font=font) > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut] + "-", font=font) > max_width:
                cut -= 1
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:cut] + "-")
            word = word[cut:]
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _text_block_size(lines: list[str], font, draw: ImageDraw.ImageDraw) -> tuple[int, int, int]:
    line_h = int(font.size * 1.18)
    width = max(int(draw.textlength(line, font=font)) for line in lines)
    return width, line_h * len(lines), line_h


def _measure(kind: str, text: str, size: int, max_text_w: int, font_path: str,
             draw: ImageDraw.ImageDraw) -> tuple[list[str], int, int]:
    """Return (wrapped lines, shape width, shape height) for a balloon."""
    font = load_font(size, font_path)
    lines = wrap_text(text, font, max_text_w, draw)
    tw, th, _ = _text_block_size(lines, font, draw)
    if kind == "narration":
        return lines, tw + 24, th + 18
    # An ellipse needs ~1.3x the text box to contain it comfortably.
    grow = 1.45 if kind == "shout" else 1.3
    return lines, int(tw * grow) + 26, int(th * grow) + 22


# --------------------------------------------------------------------------- placement
def _candidates(area: Rect, bw: int, bh: int, rtl: bool) -> list[tuple[int, int]]:
    """Possible top-left positions in reading order: rows top->bottom, x from the start side."""
    if bw > area.w or bh > area.h:
        return []
    xs_count, ys_count = 9, 9
    xs = [area.x + round(i * (area.w - bw) / (xs_count - 1)) for i in range(xs_count)]
    ys = [area.y + round(j * (area.h - bh) / (ys_count - 1)) for j in range(ys_count)]
    if rtl:
        xs = list(reversed(xs))
    return [(x, y) for y in ys for x in xs]


def _find_spot(area: Rect, bw: int, bh: int, keep_out: Rect, placed: list[Rect], rtl: bool) -> Rect | None:
    for x, y in _candidates(area, bw, bh, rtl):
        box = Rect(x, y, bw, bh)
        if box.intersects(keep_out):
            continue
        if any(box.intersects(p.inset(-BALLOON_GAP)) for p in placed):
            continue
        return box
    return None


def plan_balloons(panel: Panel, rect: Rect, *, font_size: int = 26, font_path: str = "",
                  rtl: bool = False, draw: ImageDraw.ImageDraw | None = None) -> list[Balloon]:
    """Decide what goes where (no drawing). `rect` is the panel's inner area."""
    if draw is None:
        from PIL import Image
        draw = ImageDraw.Draw(Image.new("L", (1, 1)))

    items: list[tuple[str, str, str | None]] = []  # (kind, text, speaker)
    if panel.narration:
        items.append(("narration", safe_text(panel.narration, font_path), None))
    for line in panel.dialogue:
        shout = line.text.rstrip().endswith("!") and panel.mood.lower() in ("dramatic", "tense")
        items.append(("shout" if shout else "speech", safe_text(line.text, font_path).upper(), line.speaker))

    area = rect.inset(EDGE_PAD)
    keep_out = keep_out_zone(rect)
    placed: list[Rect] = []
    balloons: list[Balloon] = []

    for kind, text, speaker in items:
        balloon = None
        size = font_size
        width_ratio = 0.42 if kind != "narration" else 0.5
        while balloon is None:
            max_text_w = max(80, int(rect.w * width_ratio) - 30)
            lines, bw, bh = _measure(kind, text, size, max_text_w, font_path, draw)
            box = _find_spot(area, bw, bh, keep_out, placed, rtl)
            if box:
                balloon = Balloon(kind, lines, size, box)
            elif size > MIN_FONT:
                size = max(MIN_FONT, size - 2)
            elif width_ratio < 0.48:
                width_ratio += 0.03   # wider + shorter can fit in the top band
            else:
                # Last resort: top corner of reading start, clipped to the panel.
                bw, bh = min(bw, area.w), min(bh, area.h)
                x = area.right - bw if rtl else area.x
                balloon = Balloon(kind, lines, size, Rect(x, area.y, bw, bh), overflow=True)
        if kind != "narration" and speaker is not None:
            names = [n.lower() for n in panel.characters]
            if speaker.lower() in names:
                i = names.index(speaker.lower())
                balloon.tail_target = (rect.x + rect.w * character_x_fraction(i, len(names)),
                                       rect.y + rect.h * 0.55)
        balloon.meta["speaker"] = speaker
        placed.append(balloon.box)
        balloons.append(balloon)
    return balloons


# --------------------------------------------------------------------------- drawing
def _ellipse_edge(cx: float, cy: float, a: float, b: float, angle: float) -> tuple[float, float]:
    dx, dy = math.cos(angle), math.sin(angle)
    t = 1 / math.sqrt((dx / a) ** 2 + (dy / b) ** 2)
    return cx + dx * t, cy + dy * t


def _draw_tail(draw: ImageDraw.ImageDraw, box: Rect, target: tuple[float, float], panel: Rect) -> None:
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    a, b = box.w / 2, box.h / 2
    angle = math.atan2(target[1] - cy, target[0] - cx)
    spread = 0.22
    base1 = _ellipse_edge(cx, cy, a * 0.9, b * 0.9, angle - spread)
    base2 = _ellipse_edge(cx, cy, a * 0.9, b * 0.9, angle + spread)
    edge = _ellipse_edge(cx, cy, a, b, angle)
    length = min(math.dist(edge, target) * 0.6, panel.h * 0.12, 70)
    tip = (edge[0] + math.cos(angle) * length, edge[1] + math.sin(angle) * length)
    tip = (min(max(tip[0], panel.x + 4), panel.right - 4), min(max(tip[1], panel.y + 4), panel.bottom - 4))
    # White fill covers the ellipse outline at the tail's base, so they look joined.
    draw.polygon([base1, tip, base2], fill=PAPER)
    draw.line([base1, tip], fill=INK, width=LINE_W)
    draw.line([base2, tip], fill=INK, width=LINE_W)


def _shout_polygon(box: Rect, spikes: int = 18) -> list[tuple[float, float]]:
    cx, cy = box.x + box.w / 2, box.y + box.h / 2
    points = []
    for k in range(spikes * 2):
        angle = math.pi * k / spikes
        r = 1.0 if k % 2 == 0 else 0.84
        points.append((cx + math.cos(angle) * box.w / 2 * r, cy + math.sin(angle) * box.h / 2 * r))
    return points


def draw_balloons(draw: ImageDraw.ImageDraw, balloons: list[Balloon], panel: Rect, font_path: str = "") -> None:
    for balloon in balloons:
        box = balloon.box
        font = load_font(balloon.font_size, font_path)
        if balloon.kind == "narration":
            draw.rectangle(box.box, fill=PAPER, outline=INK, width=LINE_W)
        elif balloon.kind == "shout":
            draw.polygon(_shout_polygon(box), fill=PAPER, outline=INK, width=LINE_W)
        else:
            draw.ellipse(box.box, fill=PAPER, outline=INK, width=LINE_W)
        if balloon.tail_target:
            _draw_tail(draw, box, balloon.tail_target, panel)

        line_h = int(font.size * 1.18)
        block_h = line_h * len(balloon.lines)
        y = box.y + (box.h - block_h) / 2 + line_h / 2
        for line in balloon.lines:
            if balloon.kind == "narration":
                draw.text((box.x + 12, y), line, fill=INK, font=font, anchor="lm")
            else:
                draw.text((box.x + box.w / 2, y), line, fill=INK, font=font, anchor="mm")
            y += line_h


def letter_panel(draw: ImageDraw.ImageDraw, panel: Panel, rect: Rect, *, font_size: int = 26,
                 font_path: str = "", rtl: bool = False, debug_keep_out: bool = False) -> list[Balloon]:
    """Plan and draw all text for one panel. Returns the balloons (for tests/debug)."""
    balloons = plan_balloons(panel, rect, font_size=font_size, font_path=font_path, rtl=rtl, draw=draw)
    if debug_keep_out:
        draw.rectangle(keep_out_zone(rect).box, outline=128, width=2)
    draw_balloons(draw, balloons, rect, font_path)
    return balloons
