"""Anime face detection (CPU, lightweight) — used to crop reference sheets and to letter around faces.

How it works: `lbpcascade_animeface` (nagadomi, MIT licence, the file in vision/models/) is an OpenCV
*cascade classifier*. It slides a window over the image at many sizes and, at each spot, runs a chain
of very cheap texture tests (LBP = "local binary patterns": is each pixel brighter than its
neighbours?). A spot that passes every stage of the chain is reported as a face. It was trained on
anime/manga faces, so it finds drawn faces (big eyes, simple noses) where photo face detectors fail,
and it needs no GPU and no download: a few milliseconds per panel.

Limitations: it misses faces seen from the side/back and very small or very stylised faces, and can
fire on face-like patterns. Callers therefore fall back to *estimated* positions (where the prompt
builder told the image model to put the characters) when nothing is found.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image

from ..geometry import Rect, character_x_fraction

log = logging.getLogger("manga.faces")
CASCADE = Path(__file__).parent / "models" / "lbpcascade_animeface.xml"


@dataclass(frozen=True)
class Face:
    x: int
    y: int
    w: int
    h: int
    detected: bool = True     # False = an estimate, not a detection

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.h)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def scaled(self, sx: float, sy: float, dx: float = 0, dy: float = 0) -> "Face":
        return Face(round(self.x * sx + dx), round(self.y * sy + dy), round(self.w * sx), round(self.h * sy), self.detected)


@lru_cache(maxsize=1)
def _cascade():
    try:
        import cv2  # optional dependency (opencv-python-headless)
    except ImportError:
        return None
    if not CASCADE.exists():
        return None
    classifier = cv2.CascadeClassifier(str(CASCADE))
    return None if classifier.empty() else classifier


def available() -> bool:
    return _cascade() is not None


def _overlap(a: Face, b: Face) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy / max(1, min(a.w * a.h, b.w * b.h))


def detect_faces(image: Image.Image | Path | str, min_size: float = 0.05, max_side: int = 1024) -> list[Face]:
    """Faces in the image (pixel coordinates of the original), biggest first. [] if OpenCV is missing."""
    cascade = _cascade()
    if cascade is None:
        return []
    import cv2
    import numpy as np

    img = Image.open(image) if isinstance(image, (str, Path)) else image
    grey = img.convert("L")
    scale = min(1.0, max_side / max(grey.size))   # detection on a smaller copy is faster and just as good
    if scale < 1.0:
        grey = grey.resize((round(grey.width * scale), round(grey.height * scale)))
    pixels = cv2.equalizeHist(np.asarray(grey))  # even out contrast (screentone, faded ink)
    smallest = max(24, int(min(grey.size) * min_size))
    found = cascade.detectMultiScale(pixels, scaleFactor=1.1, minNeighbors=5, minSize=(smallest, smallest))
    faces = sorted((Face(int(x / scale), int(y / scale), int(w / scale), int(h / scale)) for x, y, w, h in found),
                   key=lambda f: f.w * f.h, reverse=True)
    kept: list[Face] = []
    for face in faces:                      # drop duplicates of the same face at another size
        if all(_overlap(face, k) < 0.5 for k in kept):
            kept.append(face)
    return kept


def reading_order(faces: list[Face], rtl: bool = False) -> list[Face]:
    """Rows top to bottom (faces whose centres are within half a face height share a row)."""
    rows: list[list[Face]] = []
    for face in sorted(faces, key=lambda f: f.center[1]):
        if rows and abs(rows[-1][0].center[1] - face.center[1]) < face.h * 0.6:
            rows[-1].append(face)
        else:
            rows.append([face])
    return [f for row in rows for f in sorted(row, key=lambda f: f.center[0], reverse=rtl)]


# How big a face usually is, relative to the panel height, for each shot type.
SHOT_FACE = {"extreme close-up": 0.7, "close-up": 0.45, "medium": 0.22, "over-the-shoulder": 0.25,
             "wide": 0.1, "establishing": 0.05}


def estimated_faces(width: int, height: int, count: int, shot: str = "medium") -> list[Face]:
    """Where faces probably are when detection finds nothing: characters spread left to right
    (the same positions the mock image provider draws and the old tail logic assumed)."""
    if count <= 0:
        return []
    size = int(height * SHOT_FACE.get(shot, 0.22))
    top = int(height * (0.08 if shot in ("close-up", "extreme close-up") else 0.18))
    faces = []
    for i in range(count):
        cx = width * character_x_fraction(i, count)
        faces.append(Face(int(cx - size / 2), top, size, size, detected=False))
    return faces


def crop_around(image: Image.Image, face: Face, wide: float = 2.2, tall: float = 2.8, up: float = 0.55) -> Image.Image:
    """Head-and-shoulders crop around a face (for IP-Adapter references): `wide`/`tall` face sizes,
    with `up` of the extra height above the face (hair) and the rest below (neck, shoulders)."""
    w, h = face.w * wide, face.h * tall
    cx = face.center[0]
    top = face.y - (h - face.h) * up
    box = (max(0, int(cx - w / 2)), max(0, int(top)), min(image.width, int(cx + w / 2)), min(image.height, int(top + h)))
    return image.crop(box)
