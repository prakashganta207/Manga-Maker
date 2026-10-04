"""Mock image provider: draws manga-flavoured placeholder panels with Pillow.

Each placeholder shows the camera shot (wide = small full-body figures,
medium = half bodies, close-up = one big face), the characters (labelled),
screentone dots and, for dramatic moods, speed lines. Deterministic per seed.
"""

from __future__ import annotations

import hashlib
import math
import random

from PIL import Image, ImageDraw

from ..fonts import load_font, safe_text
from ..geometry import character_x_fraction
from .base import ImageProvider, ImageRequest

INK = 0
PAPER = 255


def _name_seed(name: str) -> int:
    return int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)


def _screentone(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], spacing: int, radius: int) -> None:
    """Halftone dots — the classic printed-manga grey."""
    x0, y0, x1, y1 = box
    for row, y in enumerate(range(y0, y1, spacing)):
        offset = spacing // 2 if row % 2 else 0
        for x in range(x0 + offset, x1, spacing):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=INK)


def _speed_lines(draw: ImageDraw.ImageDraw, w: int, h: int, rng: random.Random) -> None:
    cx, cy = w / 2, h / 2
    reach = math.hypot(w, h)
    for _ in range(70):
        angle = rng.uniform(0, 2 * math.pi)
        inner = rng.uniform(0.32, 0.45) * min(w, h)
        x0, y0 = cx + math.cos(angle) * inner, cy + math.sin(angle) * inner
        x1, y1 = cx + math.cos(angle) * reach, cy + math.sin(angle) * reach
        draw.line((x0, y0, x1, y1), fill=INK, width=rng.choice([1, 1, 2]))


def _figure(draw: ImageDraw.ImageDraw, cx: float, ground: float, height: float, name: str, crop: str,
            show_name: bool = True) -> None:
    """A simple ink figure. crop: 'full' (wide), 'half' (medium), 'head' (close-up)."""
    s = _name_seed(name)
    head_r = height * (0.13 if crop == "full" else 0.2 if crop == "half" else 0.42)
    if crop == "full":
        head_cy = ground - height + head_r
    elif crop == "half":
        head_cy = ground - height * 0.62
    else:
        head_cy = ground - height * 0.48
    line_w = max(2, int(head_r / 10))

    # Body
    if crop != "head":
        body_top = head_cy + head_r * 0.9
        body_bottom = ground if crop == "half" else ground - height * 0.38
        shoulder = head_r * 1.6
        draw.polygon([(cx - shoulder, body_bottom), (cx - shoulder * 0.7, body_top),
                      (cx + shoulder * 0.7, body_top), (cx + shoulder, body_bottom)],
                     fill=PAPER, outline=INK, width=line_w)
        if crop == "full":  # legs
            draw.line((cx - shoulder * 0.4, body_bottom, cx - shoulder * 0.5, ground), fill=INK, width=line_w * 2)
            draw.line((cx + shoulder * 0.4, body_bottom, cx + shoulder * 0.5, ground), fill=INK, width=line_w * 2)
    else:  # shoulders peeking at the bottom of a close-up
        draw.pieslice((cx - head_r * 2.2, ground - head_r * 0.6, cx + head_r * 2.2, ground + head_r * 2.4),
                      180, 360, fill=PAPER, outline=INK, width=line_w)

    # Head
    head = (cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r)
    draw.ellipse(head, fill=PAPER, outline=INK, width=line_w)
    # Hair: solid black cap, shape varies per character (consistent across panels)
    # Chord across the top of the head; angles vary per character but keep the eyes visible.
    hair_start = 185 + (s % 15)
    hair_end = 355 - (s % 15)
    draw.chord(head, hair_start, hair_end, fill=INK)
    if s % 3 == 0:  # spikes
        for k in range(5):
            a = math.radians(200 + k * 35)
            draw.polygon([(cx + math.cos(a) * head_r * 0.8, head_cy + math.sin(a) * head_r * 0.8),
                          (cx + math.cos(a + 0.25) * head_r * 1.35, head_cy + math.sin(a + 0.25) * head_r * 1.35),
                          (cx + math.cos(a + 0.5) * head_r * 0.8, head_cy + math.sin(a + 0.5) * head_r * 0.8)], fill=INK)
    # Eyes
    eye_y = head_cy + head_r * 0.15
    eye_dx = head_r * 0.38
    eye_r = max(2, head_r * 0.13)
    for ex in (cx - eye_dx, cx + eye_dx):
        draw.ellipse((ex - eye_r * 0.7, eye_y - eye_r, ex + eye_r * 0.7, eye_y + eye_r), fill=INK)
    # Name tag under the figure (placeholder only)
    font = load_font(max(12, int(head_r * (0.5 if crop != "head" else 0.25))))
    name = safe_text(name)
    if not show_name:
        return
    if crop == "head":
        draw.text((cx, ground - 8), name, fill=INK, font=font, anchor="md", stroke_width=3, stroke_fill=PAPER)
    else:
        draw.text((cx, head_cy - head_r - 6), name, fill=INK, font=font, anchor="md",
                  stroke_width=3, stroke_fill=PAPER)


class MockImageProvider(ImageProvider):
    name = "mock"

    def generate(self, request: ImageRequest) -> Image.Image:
        w, h = max(64, request.width), max(64, request.height)
        rng = random.Random(request.seed)
        img = Image.new("L", (w, h), PAPER)
        draw = ImageDraw.Draw(img)
        meta = request.metadata

        if request.kind == "character_ref":
            return self._character_ref(img, draw, meta)

        shot = meta.get("shot", "medium")
        names: list[str] = meta.get("characters") or []
        mood = meta.get("mood", "calm")

        # Background: screentone sky/ground depending on shot
        if shot == "wide":
            horizon = int(h * 0.62)
            _screentone(draw, (0, horizon, w, h), spacing=9, radius=2)
            draw.line((0, horizon, w, horizon), fill=INK, width=3)
        elif mood in ("tense", "mysterious", "melancholy"):
            _screentone(draw, (0, 0, w, h), spacing=8, radius=2)
        else:
            _screentone(draw, (0, 0, w, int(h * 0.3)), spacing=10, radius=1)
        if mood == "dramatic":
            _speed_lines(draw, w, h, rng)

        # Figures — placed at the same x positions the bubble tails will target
        count = len(names)
        for i, name in enumerate(names):
            cx = w * character_x_fraction(i, count)
            if shot == "wide":
                _figure(draw, cx, h * 0.85, h * 0.45, name, "full")
            elif shot == "medium":
                _figure(draw, cx, h, h * 0.8, name, "half")
            else:
                _figure(draw, cx, h, h * (0.95 if count == 1 else 0.55), name, "head")

        # Label (bottom-left): shot + characters, so you can check the script at a glance
        label = safe_text(f"{shot.upper()} · {', '.join(names) or 'no characters'}")
        font = load_font(max(12, min(w, h) // 32))
        bbox = draw.textbbox((10, h - 10), label, font=font, anchor="ld")
        draw.rectangle((bbox[0] - 6, bbox[1] - 4, bbox[2] + 6, bbox[3] + 4), fill=PAPER, outline=INK, width=2)
        draw.text((10, h - 10), label, fill=INK, font=font, anchor="ld")
        return img

    def _character_ref(self, img: Image.Image, draw: ImageDraw.ImageDraw, meta: dict) -> Image.Image:
        w, h = img.size
        name = meta.get("name", "Character")
        _screentone(draw, (0, int(h * 0.9), w, h), spacing=9, radius=2)
        _figure(draw, w * 0.5, h * 0.92, h * 0.6, name, "full", show_name=False)
        font = load_font(max(14, w // 18))
        draw.text((w / 2, 16), safe_text(f"{name} - reference"), fill=INK, font=font, anchor="mt")
        small = load_font(max(11, w // 34))
        y = 16 + font.size * 1.5
        for line in meta.get("description_lines", [])[:3]:
            draw.text((w / 2, y), safe_text(line[:60]), fill=INK, font=small, anchor="mt")
            y += small.size * 1.3
        return img
