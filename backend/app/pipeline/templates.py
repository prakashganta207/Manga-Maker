"""Library of manga page layout templates (plain geometry, no AI).

Each template is a list of panel slots in reading order (left-to-right). Coordinates are
fractions of the page's inner area (inside the margins). Right-to-left pages mirror the
template horizontally, so slot 1 ends up top-right.

A slot's size class (splash / large / medium / small) comes from its area, so the
Director can match the Writer's panel sizes (e.g. climax = large) to a template.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..geometry import Rect

SIZE_RANK = {"small": 0, "medium": 1, "large": 2, "splash": 3}


@dataclass(frozen=True)
class Slot:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def size(self) -> str:
        if self.area >= 0.99:
            return "splash"
        if self.area >= 0.38:
            return "large"
        if self.area >= 0.14:
            return "medium"
        return "small"

    @property
    def shape(self) -> str:
        ratio = self.w / self.h
        return "tall" if ratio < 0.75 else "wide" if ratio > 1.6 else "square-ish"


@dataclass(frozen=True)
class LayoutTemplate:
    id: str
    name: str
    description: str
    slots: tuple[Slot, ...]

    @property
    def panel_count(self) -> int:
        return len(self.slots)

    @property
    def sizes(self) -> list[str]:
        return [s.size for s in self.slots]

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "panels": self.panel_count, "description": self.description,
                "slots": [{"size": s.size, "shape": s.shape, "x": s.x, "y": s.y, "w": s.w, "h": s.h}
                          for s in self.slots]}


T = 1 / 3
TEMPLATES: tuple[LayoutTemplate, ...] = (
    LayoutTemplate("splash", "Splash page", "One full-page panel for the climax or a huge reveal.",
                   (Slot(0, 0, 1, 1),)),
    LayoutTemplate("two_tier", "Two tiers", "Two wide panels stacked: a beat and its answer.",
                   (Slot(0, 0, 1, 0.5), Slot(0, 0.5, 1, 0.5))),
    LayoutTemplate("three_tier", "Three tiers", "Three full-width rows, no diagonals: calm, steady storytelling.",
                   (Slot(0, 0, 1, T), Slot(0, T, 1, T), Slot(0, 2 * T, 1, 1 - 2 * T))),
    LayoutTemplate("splash_top", "Big top", "A large panel on top (reveal / establishing) and two reactions below.",
                   (Slot(0, 0, 1, 0.6), Slot(0, 0.6, 0.5, 0.4), Slot(0.5, 0.6, 0.5, 0.4))),
    LayoutTemplate("classic_4", "Classic four", "Wide top, two side by side, wide bottom: the workhorse page.",
                   (Slot(0, 0, 1, 0.28), Slot(0, 0.28, 0.55, 0.4), Slot(0.55, 0.28, 0.45, 0.4),
                    Slot(0, 0.68, 1, 0.32))),
    LayoutTemplate("four_koma", "Four-koma", "Four equal stacked strips: comic timing, setup → punchline.",
                   (Slot(0, 0, 1, 0.25), Slot(0, 0.25, 1, 0.25), Slot(0, 0.5, 1, 0.25), Slot(0, 0.75, 1, 0.25))),
    LayoutTemplate("tall_left", "Tall panel", "A tall vertical panel (full body, falling, towering) beside three beats.",
                   (Slot(0, 0, 0.42, 1), Slot(0.42, 0, 0.58, T), Slot(0.42, T, 0.58, T), Slot(0.42, 2 * T, 0.58, 1 - 2 * T))),
    LayoutTemplate("action_5", "Action burst", "Two quick small panels, a large impact panel, two follow-ups.",
                   (Slot(0, 0, 0.5, 0.22), Slot(0.5, 0, 0.5, 0.22), Slot(0, 0.22, 1, 0.42),
                    Slot(0, 0.64, 0.5, 0.36), Slot(0.5, 0.64, 0.5, 0.36))),
    LayoutTemplate("dialogue_5", "Conversation", "A wide establishing strip, then a 2x2 grid for back-and-forth.",
                   (Slot(0, 0, 1, 0.28), Slot(0, 0.28, 0.5, 0.36), Slot(0.5, 0.28, 0.5, 0.36),
                    Slot(0, 0.64, 0.5, 0.36), Slot(0.5, 0.64, 0.5, 0.36))),
    LayoutTemplate("grid_6", "Six grid", "Three rows of two: dense, fast-moving page.",
                   tuple(Slot(c * 0.5, r * T, 0.5, T if r < 2 else 1 - 2 * T) for r in range(3) for c in range(2))),
)

BY_ID = {t.id: t for t in TEMPLATES}


def get(template_id: str) -> LayoutTemplate:
    if template_id not in BY_ID:
        raise KeyError(f"Unknown layout template '{template_id}'")
    return BY_ID[template_id]


def for_count(count: int) -> list[LayoutTemplate]:
    return [t for t in TEMPLATES if t.panel_count == count]


def best_template(sizes: list[str]) -> LayoutTemplate:
    """The template whose slot sizes best match the planned panel sizes (in order)."""
    options = for_count(len(sizes))
    if not options:
        raise ValueError(f"No layout template for {len(sizes)} panels (supported: 1-6)")

    def mismatch(t: LayoutTemplate) -> int:
        return sum(abs(SIZE_RANK[a] - SIZE_RANK[b]) for a, b in zip(t.sizes, sizes))

    return min(options, key=mismatch)  # ties -> first in library order


def slot_rects(template: LayoutTemplate, width: int, height: int, margin: int, gutter: int,
               rtl: bool = False) -> list[Rect]:
    """Pixel rectangles for each slot, in reading order, with gutters between panels."""
    inner_w, inner_h = width - 2 * margin, height - 2 * margin
    half = gutter / 2
    rects = []
    for s in template.slots:
        x0, x1 = s.x, s.x + s.w
        if rtl:
            x0, x1 = 1 - x1, 1 - x0
        left = margin + x0 * inner_w + (half if x0 > 0.001 else 0)
        right = margin + x1 * inner_w - (half if x1 < 0.999 else 0)
        top = margin + s.y * inner_h + (half if s.y > 0.001 else 0)
        bottom = margin + (s.y + s.h) * inner_h - (half if s.y + s.h < 0.999 else 0)
        rects.append(Rect(round(left), round(top), round(right - left), round(bottom - top)))
    return rects
