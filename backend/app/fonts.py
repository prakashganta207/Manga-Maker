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


_REPLACEMENTS = {"—": "-", "–": "-", "‒": "-", "−": "-", " ": " "}


def safe_text(text: str, font_path: str = "") -> str:
    """Make text drawable with Pillow's bundled font, which lacks dashes and accents.

    With a custom LETTERING_FONT the text is left alone (assume the font covers it).
    """
    if font_path:
        return text
    import unicodedata

    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    # "é" -> "e" + accent mark -> "e"
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
