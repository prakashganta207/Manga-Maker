"""Fonts for lettering: a free comic font for dialogue, a punchy one for sound effects.

Bundled (SIL Open Font License 1.1, licence files next to the fonts in backend/assets/fonts/):
  - Comic Neue Bold   — dialogue, narration (clean, very readable comic lettering)
  - Bangers Regular   — sound effects (heavy, slanted display letters)
`LETTERING_FONT` overrides the dialogue font. Neither bundled font has Japanese/Chinese glyphs,
so CJK text uses `LETTERING_CJK_FONT` or a system CJK font if one is installed.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DIALOGUE_FONT = ASSETS / "ComicNeue-Bold.ttf"
SFX_FONT = ASSETS / "Bangers-Regular.ttf"

_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff00-\uffef]")
_CJK_CANDIDATES = [
    "C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/msgothic.ttc", "C:/Windows/Fonts/meiryob.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def dialogue_font(custom: str = "") -> str:
    """The font file for dialogue: LETTERING_FONT if set, else the bundled Comic Neue."""
    if custom:
        return custom
    return str(DIALOGUE_FONT) if DIALOGUE_FONT.exists() else ""


def sfx_font() -> str:
    return str(SFX_FONT) if SFX_FONT.exists() else ""


@lru_cache(maxsize=1)
def cjk_font() -> str:
    for path in [os.environ.get("LETTERING_CJK_FONT", ""), *_CJK_CANDIDATES]:
        if path and Path(path).exists():
            return path
    return ""


def font_for(text: str, path: str) -> str:
    """Switch to a CJK font when the text needs one (and one is available)."""
    return (cjk_font() or path) if has_cjk(text) else path


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


_REPLACEMENTS = {"—": "-", "–": "-", "‒": "-", "−": "-", " ": " "}


def safe_text(text: str, font_path: str = "") -> str:
    """Make text drawable with Pillow's bundled font, which lacks dashes and accents.

    With a real font file the text is left alone (assume the font covers it).
    """
    if font_path:
        return text
    import unicodedata

    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    # "é" -> "e" + accent mark -> "e"
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
