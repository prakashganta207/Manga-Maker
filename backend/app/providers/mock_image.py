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

        if request.kind == "inpaint":
            return self._inpaint(request, rng)
        if request.kind == "character_ref":
            return self._character_ref(img, draw, meta)
        if request.kind == "turnaround":
            return self._turnaround(img, draw, meta)
        if request.kind == "expressions":
            return self._expressions(img, draw, meta)

        shot = meta.get("shot", "medium")
        angle = meta.get("angle", "eye level")
        names: list[str] = meta.get("characters") or []
        mood = str(meta.get("mood", "calm")).lower()

        # Background: screentone sky/ground depending on shot and angle
        if shot in ("wide", "establishing"):
            horizon = int(h * (0.35 if angle in ("high", "bird's eye") else 0.75 if angle == "low" else 0.62))
            _screentone(draw, (0, horizon, w, h), spacing=9, radius=2)
            draw.line((0, horizon, w, horizon), fill=INK, width=3)
            if shot == "establishing":  # a few buildings on the horizon
                for k in range(7):
                    bx = int(w * (k + 0.2) / 7)
                    bh = int(h * (0.08 + 0.12 * ((request.seed >> k) % 3) / 2))
                    draw.rectangle((bx, horizon - bh, bx + w // 10, horizon), fill=PAPER, outline=INK, width=2)
        elif any(m in mood for m in ("tense", "mysterious", "melancholy", "sad", "fear")):
            _screentone(draw, (0, 0, w, h), spacing=8, radius=2)
        else:
            _screentone(draw, (0, 0, w, int(h * 0.3)), spacing=10, radius=1)
        if "dramatic" in mood or angle == "low":
            _speed_lines(draw, w, h, rng)

        # Figures — placed at the same x positions the bubble tails will target
        count = len(names)
        for i, name in enumerate(names):
            cx = w * character_x_fraction(i, count)
            if shot == "establishing":
                _figure(draw, cx, h * 0.8, h * 0.2, name, "full")
            elif shot == "wide":
                _figure(draw, cx, h * 0.85, h * 0.45, name, "full")
            elif shot in ("medium", "over-the-shoulder"):
                _figure(draw, cx, h, h * 0.8, name, "half")
            elif shot == "extreme close-up":
                _figure(draw, cx, h * 1.25, h * (1.3 if count == 1 else 0.8), name, "head")
            else:
                _figure(draw, cx, h, h * (0.95 if count == 1 else 0.55), name, "head")
        if shot == "over-the-shoulder":  # dark shoulder + head of the listener in the foreground
            draw.ellipse((-w * 0.15, h * 0.35, w * 0.35, h * 1.2), fill=INK)
            draw.ellipse((w * 0.02, h * 0.2, w * 0.3, h * 0.55), fill=INK)

        # Label (bottom-left): shot + angle + characters, so you can check the director's plan
        label = safe_text(f"{shot.upper()} / {angle} · {', '.join(names) or 'no characters'}")
        font = load_font(max(12, min(w, h) // 32))
        bbox = draw.textbbox((10, h - 10), label, font=font, anchor="ld")
        draw.rectangle((bbox[0] - 6, bbox[1] - 4, bbox[2] + 6, bbox[3] + 4), fill=PAPER, outline=INK, width=2)
        draw.text((10, h - 10), label, fill=INK, font=font, anchor="ld")
        return img

    def supports_controlnet(self) -> bool:
        return True

    def preprocess(self, image, mode: str) -> Image.Image:
        """Mock control images (ControlNet convention: white on black). "openpose": a stick figure
        where the rough has ink (all black = no pose found); "lineart": the rough's edges."""
        from PIL import ImageFilter, ImageStat
        rough = Image.open(image).convert("L")
        if mode == "lineart":
            return rough.filter(ImageFilter.FIND_EDGES).convert("RGB")
        pose = Image.new("RGB", rough.size, "black")
        if ImageStat.Stat(rough).mean[0] > 248:     # an empty rough: no pose to find
            return pose
        d = ImageDraw.Draw(pose)
        w, h = rough.size
        cx, top = w / 2, h * 0.2
        joints = {"head": (cx, top), "neck": (cx, top + h * 0.1), "hip": (cx, top + h * 0.4),
                  "lh": (cx - w * 0.15, top + h * 0.3), "rh": (cx + w * 0.15, top + h * 0.3),
                  "lf": (cx - w * 0.1, top + h * 0.7), "rf": (cx + w * 0.1, top + h * 0.7)}
        for a, b in (("head", "neck"), ("neck", "hip"), ("neck", "lh"), ("neck", "rh"), ("hip", "lf"), ("hip", "rf")):
            d.line((*joints[a], *joints[b]), fill=(255, 255, 255), width=max(3, w // 80))
        return pose

    def _inpaint(self, request: ImageRequest, rng: random.Random) -> Image.Image:
        """Mock inpainting: cross-hatching + a label inside the mask, everything else untouched."""
        base = Image.open(request.init_image).convert("L")
        mask = Image.open(request.mask_image).convert("L").resize(base.size)
        patch = Image.new("L", base.size, PAPER)
        draw = ImageDraw.Draw(patch)
        step = rng.randint(9, 14)
        for x in range(-base.height, base.width, step):
            draw.line((x, 0, x + base.height, base.height), fill=INK, width=2)
        box = mask.getbbox()
        if box:
            label = safe_text(request.metadata.get("region", "inpainted"))[:24]
            draw.rectangle((box[0] + 4, box[1] + 4, box[0] + 12 + 9 * len(label), box[1] + 30), fill=PAPER)
            draw.text((box[0] + 8, box[1] + 8), label, fill=INK, font=load_font(16))
        return Image.composite(patch, base, mask)

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

    # ------------------------------------------------------------------ character sheets
    def _turnaround(self, img: Image.Image, draw: ImageDraw.ImageDraw, meta: dict) -> Image.Image:
        """Three equal columns: front, side, back (the pipeline crops them apart)."""
        w, h = img.size
        name = meta.get("name", "Character")
        col = w / 3
        _screentone(draw, (0, int(h * 0.9), w, h), spacing=9, radius=2)
        for k, view in enumerate(("front", "side", "back")):
            cx = col * k + col / 2
            _figure(draw, cx, h * 0.9, h * 0.72, name, "full", show_name=False)
            head_r = h * 0.72 * 0.13
            head_cy = h * 0.9 - h * 0.72 + head_r
            if view == "side":  # profile: cover the far eye, add a nose
                draw.ellipse((cx - head_r * 0.9, head_cy - head_r * 0.1, cx, head_cy + head_r * 0.6), fill=PAPER)
                draw.polygon([(cx + head_r, head_cy + head_r * 0.1), (cx + head_r * 1.25, head_cy + head_r * 0.35),
                              (cx + head_r * 0.95, head_cy + head_r * 0.45)], fill=PAPER, outline=INK)
            elif view == "back":  # all hair, no face
                draw.ellipse((cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r), fill=INK)
            font = load_font(max(12, int(col / 12)))
            draw.text((cx, h * 0.05), view.upper(), fill=INK, font=font, anchor="mt")
        return img

    def _expressions(self, img: Image.Image, draw: ImageDraw.ImageDraw, meta: dict) -> Image.Image:
        """Five equal columns of faces: neutral, happy, angry, sad, surprised."""
        w, h = img.size
        name = meta.get("name", "Character")
        expressions = meta.get("expressions") or ["neutral", "happy", "angry", "sad", "surprised"]
        col = w / len(expressions)
        for k, expression in enumerate(expressions):
            cx, cy = col * k + col / 2, h * 0.56
            r = min(col, h) * 0.34
            # Head with the character's hair cap (same shape as in panels) and eyes.
            seed = _name_seed(name)
            head = (cx - r, cy - r, cx + r, cy + r)
            draw.ellipse(head, fill=PAPER, outline=INK, width=4)
            draw.chord(head, 185 + (seed % 15), 355 - (seed % 15), fill=INK)
            for ex in (cx - r * 0.38, cx + r * 0.38):
                draw.ellipse((ex - r * 0.09, cy + r * 0.05, ex + r * 0.09, cy + r * 0.3), fill=INK)
            cy = cy - r * 0.05  # features below are placed relative to this
            mouth_y = cy + r * 0.55
            if expression == "happy":
                draw.arc((cx - r * 0.35, mouth_y - r * 0.25, cx + r * 0.35, mouth_y + r * 0.2), 10, 170, fill=INK, width=4)
            elif expression == "sad":
                draw.arc((cx - r * 0.3, mouth_y, cx + r * 0.3, mouth_y + r * 0.35), 200, 340, fill=INK, width=4)
                draw.line((cx - r * 0.42, cy + r * 0.4, cx - r * 0.42, cy + r * 0.65), fill=INK, width=3)  # tear
            elif expression == "angry":
                draw.line((cx - r * 0.3, mouth_y + r * 0.1, cx + r * 0.3, mouth_y + r * 0.1), fill=INK, width=5)
                for side in (-1, 1):  # slanted brows
                    draw.line((cx + side * r * 0.15, cy + r * 0.05, cx + side * r * 0.6, cy - r * 0.12), fill=PAPER, width=10)
                    draw.line((cx + side * r * 0.15, cy + r * 0.05, cx + side * r * 0.6, cy - r * 0.12), fill=INK, width=6)
            elif expression == "surprised":
                draw.ellipse((cx - r * 0.12, mouth_y - r * 0.05, cx + r * 0.12, mouth_y + r * 0.25), outline=INK, width=4)
            else:
                draw.line((cx - r * 0.2, mouth_y + r * 0.1, cx + r * 0.2, mouth_y + r * 0.1), fill=INK, width=3)
            font = load_font(max(12, int(col / 10)))
            draw.text((cx, h * 0.06), expression.upper(), fill=INK, font=font, anchor="mt")
        return img
