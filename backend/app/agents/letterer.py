"""Letterer agent — places speech bubbles like a manga letterer would (plain code, no LLM).

For every panel:
  1. **Find the faces** in the panel art (anime face detector, vision/faces.py). If none are found,
     use the estimated positions where the characters were asked to stand.
  2. **Measure how busy the art is** everywhere: a low-resolution "busy map" of ink edges and dark
     areas. Calm areas (sky, walls, empty background) are cheap places for a bubble; detailed
     linework, faces and hands are expensive.
  3. **Place the items in reading order** (narration first, then dialogue in script order, then sound
     effects). Each candidate position gets a cost:
        busy art under the bubble  + far from its speaker  + breaking the reading order
     Hard rules: inside the panel, never on a face, never on another bubble. The cheapest wins; if
     nothing fits, the font shrinks; as a last resort a face may be covered (and it's noted).
  4. **Aim each tail at the speaker's face** (faces left-to-right = the panel's characters in order,
     the same convention the prompt builder uses), stopping short of the face.

Reading order: right-to-left by default (manga: the first bubble sits top-right, the next one to its
left or below). Text can be horizontal or vertical (Japanese-style columns), with the font size
fitted to the space. The result is a set of editable layers: you can move anything in the editor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ..fonts import font_for, has_cjk, load_font, safe_text, sfx_font
from ..geometry import Rect
from ..pipeline.lettering import MIN_FONT, SHOUT_MOODS, _measure, tail_tip
from ..pipeline.masks import visible_region
from ..vision.faces import Face, detect_faces, estimated_faces
from .schemas import PlannedPage, PlannedPanel
from .state import Bubble, PageLettering

GRID = 13            # candidate positions per axis
EDGE = 10            # px from the panel border
GAP = 8              # px between bubbles
FACE_PAD = 0.12      # faces are padded by 12% before checking overlaps


@dataclass
class PanelContext:
    panel: PlannedPanel
    rect: Rect                     # the panel's inner rectangle on the page
    faces: list[Face]              # page coordinates
    busy: "BusyMap"
    shot: str = "medium"
    notes: list[str] = field(default_factory=list)


class BusyMap:
    """How 'busy' the art is (0 = empty paper, 1 = dense ink), with fast box averages."""

    def __init__(self, image: Image.Image | None, rect: Rect, scale: int = 8):
        self.rect, self.scale = rect, scale
        w, h = max(1, rect.w // scale), max(1, rect.h // scale)
        if image is None:
            self.cells = [[0.0] * w for _ in range(h)]
        else:
            grey = image.convert("L").resize((w, h), Image.Resampling.BILINEAR)
            edges = grey.filter(ImageFilter.FIND_EDGES)
            dark = ImageOps.invert(grey)
            # Edges (linework) matter most; large dark areas (hair, shadows) a bit less.
            mixed = Image.blend(edges, dark, 0.35).filter(ImageFilter.GaussianBlur(1.2))
            data = list(mixed.tobytes())  # one byte per pixel in "L" mode
            peak = max(1, max(data))
            self.cells = [[data[y * w + x] / peak for x in range(w)] for y in range(h)]
        # Integral image -> the mean over any box in O(1).
        self.sum = [[0.0] * (w + 1) for _ in range(h + 1)]
        for y in range(h):
            row = 0.0
            for x in range(w):
                row += self.cells[y][x]
                self.sum[y + 1][x + 1] = self.sum[y][x + 1] + row
        self.w, self.h = w, h

    def mean(self, box: Rect) -> float:
        x0 = max(0, min(self.w, (box.x - self.rect.x) // self.scale))
        y0 = max(0, min(self.h, (box.y - self.rect.y) // self.scale))
        x1 = max(x0 + 1, min(self.w, math.ceil((box.right - self.rect.x) / self.scale)))
        y1 = max(y0 + 1, min(self.h, math.ceil((box.bottom - self.rect.y) / self.scale)))
        total = self.sum[y1][x1] - self.sum[y0][x1] - self.sum[y1][x0] + self.sum[y0][x0]
        return total / max(1, (x1 - x0) * (y1 - y0))


def panel_faces(image: Image.Image | None, slot: Rect, inner: Rect, count: int, shot: str) -> list[Face]:
    """Faces in page coordinates: detected on the art (undoing the cover fit) or estimated."""
    if image is not None:
        ox, oy, vw, vh = visible_region(image.size, (slot.w, slot.h))
        found = []
        for f in detect_faces(image):
            if f.center[0] < ox or f.center[0] > ox + vw or f.center[1] < oy or f.center[1] > oy + vh:
                continue  # cropped away by the cover fit
            found.append(f.scaled(slot.w / vw, slot.h / vh, slot.x - ox * slot.w / vw, slot.y - oy * slot.h / vh))
        if found:
            return found
    return [f.scaled(1, 1, inner.x, inner.y) for f in estimated_faces(inner.w, inner.h, count, shot)]


def reading_score(box: Rect, rect: Rect, rtl: bool) -> float:
    """0 = where reading starts (top-right for RTL), growing along rows then down the panel."""
    cx = (box.x + box.w / 2 - rect.x) / rect.w
    cy = (box.y + box.h / 2 - rect.y) / rect.h
    across = (1 - cx) if rtl else cx
    return cy + 0.35 * across


def speaker_face(ctx: PanelContext, speaker: str | None) -> Face | None:
    """The speaker's face: faces left to right = the panel's characters in order (how the prompt
    builder placed them). If fewer faces were detected than there are characters, we can't tell
    who is who, so we fall back to the estimated positions."""
    if not speaker:
        return None
    names = [n.lower() for n in ctx.panel.characters]
    if speaker.lower() not in names:
        return None   # an off-panel voice: no tail
    ordered = sorted(ctx.faces, key=lambda f: f.x)
    if len(ordered) < len(names):
        ordered = estimated_faces(ctx.rect.w, ctx.rect.h, len(names), ctx.shot)
        ordered = [f.scaled(1, 1, ctx.rect.x, ctx.rect.y) for f in ordered]
    return ordered[names.index(speaker.lower())]


def _padded(face: Face) -> Rect:
    px, py = int(face.w * FACE_PAD), int(face.h * FACE_PAD)
    return Rect(face.x - px, face.y - py, face.w + 2 * px, face.h + 2 * py)


def _overlap_area(a: Rect, b: Rect) -> int:
    return max(0, min(a.right, b.right) - max(a.x, b.x)) * max(0, min(a.bottom, b.bottom) - max(a.y, b.y))


def choose_spot(ctx: PanelContext, bw: int, bh: int, placed: list[Rect], previous: float, rtl: bool,
                speaker: Face | None, allow_faces: bool = False, top: float = 0.0) -> tuple[Rect, float] | None:
    area = ctx.rect.inset(EDGE)
    if bw > area.w or bh > area.h:
        return None
    faces = [_padded(f) for f in ctx.faces]
    diag = math.hypot(ctx.rect.w, ctx.rect.h)
    best: tuple[float, Rect, float] | None = None
    for j in range(GRID):
        for i in range(GRID):
            box = Rect(area.x + round(i * (area.w - bw) / (GRID - 1)), area.y + round(j * (area.h - bh) / (GRID - 1)), bw, bh)
            if any(box.intersects(p.inset(-GAP)) for p in placed):
                continue
            on_face = sum(_overlap_area(box, f) for f in faces) / max(1, box.w * box.h)   # share of the bubble on faces
            if on_face and not allow_faces:
                continue
            order = reading_score(box, ctx.rect, rtl)
            cost = 3.0 * ctx.busy.mean(box)                      # calm background is cheap
            cost += 0.6 * order                                  # earlier items near the reading start
            if order < previous - 0.02:
                cost += 4.0                                      # breaks the reading order
            if speaker is not None:
                sx, sy = speaker.center
                cost += 0.8 * math.dist((box.x + bw / 2, box.y + bh / 2), (sx, sy)) / diag
            cost += 10.0 * on_face                               # (only when forced) cover as little face as possible
            cost += top * (box.y - ctx.rect.y) / ctx.rect.h        # narration boxes like the top edge
            if best is None or cost < best[0]:
                best = (cost, box, order)
    return (best[1], best[2]) if best else None


def measure(kind: str, text: str, size: int, max_w: int, font_path: str, vertical: bool,
            draw: ImageDraw.ImageDraw) -> tuple[int, int]:
    """Outer size of a bubble for this text at this font size."""
    if vertical:
        columns = vertical_columns(text, max(2, 14))
        rows = max(len(c) for c in columns)
        w = int(len(columns) * size * 1.25) + 30
        h = int(rows * size * 1.08) + 34
        return (int(w * 1.35), int(h * 1.2)) if kind != "narration" else (w, h)
    _, w, h = _measure(kind, text, size, max_w, font_path, draw)
    return w, h


def vertical_columns(text: str, per_column: int) -> list[str]:
    """Vertical text: one column per word (long words wrap), read right to left."""
    columns = []
    for word in text.split():
        for i in range(0, len(word), per_column):
            columns.append(word[i:i + per_column])
    return columns or [""]


def letter_page(page: PlannedPage, slots: list[Rect], inners: list[Rect], images: dict[int, Image.Image | None],
                shots: dict[int, str], *, font_size: int = 26, font_path: str = "", rtl: bool = True,
                vertical: str = "auto") -> tuple[PageLettering, list[str]]:
    """Plan every bubble on a page. Returns the editable layers + notes for the agent trace."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    bubbles: list[Bubble] = []
    notes: list[str] = []
    faces_by_panel: dict[int, list[list[float]]] = {}
    for panel, slot, inner in zip(page.panels, slots, inners):
        image = images.get(panel.panel_number)
        shot = shots.get(panel.panel_number, "medium")
        faces = panel_faces(image, slot, inner, len(panel.characters), shot)
        ctx = PanelContext(panel, inner, faces, BusyMap(_visible(image, slot, inner), inner), shot)
        faces_by_panel[panel.panel_number] = [[(f.x - inner.x) / inner.w, (f.y - inner.y) / inner.h,
                                               f.w / inner.w, f.h / inner.h, 1.0 if f.detected else 0.0] for f in faces]
        placed: list[Rect] = []
        previous = -1.0
        items: list[tuple[str, str, str | None]] = []
        if panel.narration:
            items.append(("narration", panel.narration, None))
        mood = panel.emotion.lower()
        for line in panel.dialogue:
            shout = line.text.rstrip().endswith("!") and any(m in mood for m in SHOUT_MOODS)
            items.append(("shout" if shout else "speech", line.text.upper() if not has_cjk(line.text) else line.text,
                          line.speaker))
        for kind, text, speaker in items:
            path = font_for(text, font_path)
            text = safe_text(text, path)
            is_vertical = kind != "narration" and (vertical == "on" or (vertical == "auto" and has_cjk(text)))
            face = speaker_face(ctx, speaker)
            start = font_size - 4 if kind == "narration" else font_size     # captions are a little smaller
            top = 2.0 if kind == "narration" else 0.0
            spot, size, width_ratio, forced = None, start, 0.42 if kind != "narration" else 0.5, False
            while spot is None:
                bw, bh = measure(kind, text, size, max(80, int(inner.w * width_ratio) - 30), path, is_vertical, probe)
                spot = choose_spot(ctx, bw, bh, placed, previous, rtl, face, top=top)
                if spot is None and size > max(MIN_FONT, start - 8):
                    size -= 2                                    # shrink a little ...
                elif spot is None and width_ratio < 0.6 and not is_vertical:
                    width_ratio += 0.06                          # ... then try wider, flatter bubbles
                elif spot is None:
                    # No free space (e.g. a close-up face fills the panel): keep the text readable and
                    # take the spot that covers the fewest faces and the least detail.
                    size = max(MIN_FONT, start - 4)
                    bw, bh = measure(kind, text, size, max(80, int(inner.w * 0.5) - 30), path, is_vertical, probe)
                    spot = choose_spot(ctx, min(bw, inner.w - 2 * EDGE), min(bh, inner.h - 2 * EDGE), placed, previous,
                                       rtl, face, allow_faces=True, top=top)
                    forced = True
                    if spot is None:   # the panel is simply too small: top corner of reading start
                        bw, bh = min(bw, inner.w - 2 * EDGE), min(bh, inner.h - 2 * EDGE)
                        spot = (Rect(inner.right - EDGE - bw if rtl else inner.x + EDGE, inner.y + EDGE, bw, bh), previous)
            box, previous = spot
            if forced:
                ctx.notes.append(f"panel {panel.panel_number}: '{text[:20]}' had to overlap the art (no free space)")
            tail = None
            if kind in ("speech", "shout") and speaker:
                if face is not None:
                    target = (face.center[0], face.y + face.h * 0.75)      # toward the mouth / chin
                    tip = tail_tip(box, target, inner)
                    tail = ((tip[0] - inner.x) / inner.w, (tip[1] - inner.y) / inner.h)
            placed.append(box)
            bubbles.append(Bubble(
                id=f"b{page.page_number}-{panel.panel_number}-{len(bubbles) + 1}", panel=panel.panel_number, kind=kind,
                text=text, speaker=speaker, x=(box.x - inner.x) / inner.w, y=(box.y - inner.y) / inner.h,
                w=box.w / inner.w, h=box.h / inner.h, tail=tail, font_size=size, vertical=is_vertical,
                order=len(bubbles)))
        for sfx in panel.sfx:
            text = safe_text(sfx.upper(), sfx_font())
            size = int(font_size * 2.2)
            spot = None
            while spot is None and size >= 22:
                font = load_font(size, sfx_font())
                left, top, right, bottom = probe.textbbox((0, 0), text, font=font, stroke_width=6)
                spot = choose_spot(ctx, right - left + 24, bottom - top + 20, placed, -1.0, not rtl, None)
                size -= 6 if spot is None else 0
            if spot is None:
                ctx.notes.append(f"panel {panel.panel_number}: no free space for sound effect '{sfx}'")
                continue
            box, _ = spot
            placed.append(box)
            bubbles.append(Bubble(id=f"b{page.page_number}-{panel.panel_number}-{len(bubbles) + 1}",
                                  panel=panel.panel_number, kind="sfx", text=text, x=(box.x - inner.x) / inner.w,
                                  y=(box.y - inner.y) / inner.h, w=box.w / inner.w, h=box.h / inner.h,
                                  font_size=size, order=len(bubbles)))
        detected = sum(1 for f in faces if f.detected)
        notes.append(f"p{page.page_number}·{panel.panel_number}: {detected} face(s) detected"
                     + ("" if detected else f" (using {len(faces)} estimated)")
                     + f", {sum(1 for b in bubbles if b.panel == panel.panel_number)} layer(s)")
        notes.extend(ctx.notes)
    return PageLettering(page=page.page_number, bubbles=bubbles, faces=faces_by_panel), notes


def _visible(image: Image.Image | None, slot: Rect, inner: Rect) -> Image.Image | None:
    """The part of the panel image that is visible in the inner rectangle (cover fit)."""
    if image is None:
        return None
    return ImageOps.fit(image.convert("L"), (inner.w, inner.h), method=Image.Resampling.BILINEAR)


def open_image(path: Path | None) -> Image.Image | None:
    try:
        return Image.open(path).convert("RGB") if path and Path(path).exists() else None
    except OSError:
        return None
