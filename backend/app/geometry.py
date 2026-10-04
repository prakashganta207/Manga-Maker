"""Tiny geometry helpers shared by layout, lettering and the mock image provider."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def box(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) — the format Pillow expects."""
        return (self.x, self.y, self.right, self.bottom)

    def intersects(self, other: "Rect") -> bool:
        return not (self.right <= other.x or other.right <= self.x
                    or self.bottom <= other.y or other.bottom <= self.y)

    def contains(self, other: "Rect") -> bool:
        return (other.x >= self.x and other.y >= self.y
                and other.right <= self.right and other.bottom <= self.bottom)

    def inset(self, d: int) -> "Rect":
        return Rect(self.x + d, self.y + d, max(1, self.w - 2 * d), max(1, self.h - 2 * d))

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


def character_x_fraction(index: int, count: int) -> float:
    """Where (0..1 across the panel) the index-th of `count` characters stands.

    The mock image provider draws figures here, and the lettering engine points
    speech-bubble tails here, so tails point at the right person.
    """
    count = max(1, count)
    return (index + 1) / (count + 1)
