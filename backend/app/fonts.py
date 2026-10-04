"""Font loading for lettering and placeholder labels."""

from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont


@lru_cache(maxsize=64)
def load_font(size: int, path: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """A .ttf font if `path` is given, else Pillow's bundled font at `size`."""
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass  # fall back to the bundled font
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow without sized default font
        return ImageFont.load_default()
