"""Inpainting masks: what you paint in the editor -> a black/white image the size of the panel art.

An inpainting *mask* is a greyscale image as big as the picture: white (255) = "repaint this",
black (0) = "keep exactly as it is". The diffusion model only adds noise and redraws where the
mask is white, then the new region is pasted back with a soft edge, so the rest of the panel stays
pixel-identical.

The editor shows each panel image *cover-fitted* into its page slot (scaled up and centre-cropped,
like the page renderer). Strokes arrive as fractions of that slot, so we undo the cover fit to find
where they land on the original image.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter


@dataclass
class Stroke:
    points: list[tuple[float, float]]  # slot fractions (0..1), in drawing order
    size: float                        # brush diameter, as a fraction of the slot width
    erase: bool = False


def visible_region(image_size: tuple[int, int], slot_size: tuple[int, int]) -> tuple[float, float, float, float]:
    """The part of the image that is visible in the slot after a centred cover fit: (x, y, w, h)."""
    iw, ih = image_size
    sw, sh = slot_size
    scale = max(sw / iw, sh / ih)
    vw, vh = sw / scale, sh / scale
    return (iw - vw) / 2, (ih - vh) / 2, vw, vh


def rasterize(strokes: list[Stroke], image_size: tuple[int, int], slot_size: tuple[int, int]) -> Image.Image:
    """Draw the strokes (paint = white, erase = black) at the image's own resolution."""
    ox, oy, vw, vh = visible_region(image_size, slot_size)
    mask = Image.new("L", image_size, 0)
    draw = ImageDraw.Draw(mask)
    for stroke in strokes:
        width = max(2, round(stroke.size * vw))
        colour = 0 if stroke.erase else 255
        pts = [(ox + x * vw, oy + y * vh) for x, y in stroke.points]
        if len(pts) > 1:
            draw.line(pts, fill=colour, width=width, joint="curve")
        for x, y in pts:  # round caps and single clicks
            r = width / 2
            draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    return mask


def coverage(mask: Image.Image) -> float:
    """Fraction of the image that will be repainted."""
    histogram = mask.convert("L").histogram()
    return sum(histogram[128:]) / max(1, mask.width * mask.height)


def bbox(mask: Image.Image) -> tuple[int, int, int, int] | None:
    return mask.point(lambda v: 255 if v >= 128 else 0).getbbox()


def soften(mask: Image.Image, radius: float = 2.0) -> Image.Image:
    """Slight blur so hand-painted edges aren't jagged (the workflow also grows + feathers it)."""
    return mask.filter(ImageFilter.GaussianBlur(radius)) if radius > 0 else mask
