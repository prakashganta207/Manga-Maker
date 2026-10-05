"""Prompt builder — Director panel spec + character bible -> image prompt.

How text-to-image prompts work (short version):
- Diffusion models read comma-separated *tags*. Earlier tags weigh more, so style and
  framing come first, then who is in the panel, then what happens, then details.
- Anime checkpoints (like Animagine XL) were trained on booru-style tags such as
  "monochrome", "greyscale", "from below", "solo", "upper body" — so we map our shot
  types and camera angles to those strong, well-known tags.
- The *negative prompt* lists what to steer away from (colour, text, broken hands...).
- No text is ever requested: speech bubbles are lettered later in code.
"""

from __future__ import annotations

from pathlib import Path

from .schemas import CLOSE_SHOTS, DirectedPanel, PlannedPanel
from .state import CharacterEntry

STYLE_PREFIX = "monochrome, greyscale, manga, comic panel"
STYLE_SUFFIX = ("ink lineart, screentone shading, high contrast, clean lines, detailed background, "
                "masterpiece, best quality")
NEGATIVE_PROMPT = ("color, colorful, photorealistic, photo, 3d, render, text, letters, speech bubble, caption, "
                   "signature, watermark, logo, lowres, blurry, jpeg artifacts, bad anatomy, bad hands, "
                   "extra fingers, missing fingers, extra limbs, deformed, duplicate, cropped head, "
                   "worst quality, low quality")

SHOT_TAGS = {
    "extreme close-up": "extreme close-up, face focus, eyes in focus, detailed face",
    "close-up": "close-up, portrait, face focus, head and shoulders",
    "medium": "medium shot, upper body",
    "wide": "wide shot, full body",
    "establishing": "establishing shot, wide view, scenery, detailed background, small figures in distance",
    "over-the-shoulder": "over-the-shoulder shot, from behind, foreground shoulder, depth of field",
}
ANGLE_TAGS = {
    "eye level": "eye level",
    "low": "from below, low angle, dramatic perspective",
    "high": "from above, high angle",
    "bird's eye": "bird's eye view, from above, top-down view",
}
COUNT_TAGS = {0: "no humans, scenery", 1: "solo", 2: "two people", 3: "three people"}

# Emotion words -> one of the five expression-sheet faces.
EXPRESSION_WORDS = {
    "happy": ("happy", "joy", "cheer", "smile", "laugh", "relief", "love", "excite", "warm", "hope", "proud", "fun"),
    "angry": ("angry", "anger", "rage", "furious", "frustrat", "annoy", "determin", "defiant"),
    "sad": ("sad", "grief", "melanchol", "tear", "despair", "lonely", "regret", "sorrow", "heartbr"),
    "surprised": ("surpris", "shock", "awe", "stun", "fear", "scared", "afraid", "panic", "wonder", "mysteri"),
}
EXPRESSION_TAGS = {
    "neutral": "calm expression",
    "happy": "smile, happy",
    "angry": "angry, furrowed brow, clenched teeth",
    "sad": "sad, tears, downcast eyes",
    "surprised": "surprised, wide eyes, open mouth",
}
MOOD_TAGS = {
    "tense": "tense atmosphere, heavy shadows", "dramatic": "speed lines, dynamic pose, intense",
    "melancholy": "rain, quiet atmosphere", "cheerful": "bright, sparkles", "calm": "soft light, peaceful",
    "mysterious": "glowing light, deep shadows, mysterious",
}


def expression_for(emotion: str) -> str:
    e = emotion.lower()
    for expression, words in EXPRESSION_WORDS.items():
        if any(w in e for w in words):
            return expression
    return "neutral"


def choose_reference(character: CharacterEntry, emotion: str) -> tuple[str | None, str]:
    """Pick the best reference image for IP-Adapter: the expression that matches the panel's
    emotion if we have it, else the front view, else the whole turnaround sheet."""
    expression = expression_for(emotion)
    sheets = character.sheets
    if expression in sheets.expression_refs:
        return sheets.expression_refs[expression], expression
    if "front" in sheets.views:
        return sheets.views["front"], "front"
    if sheets.turnaround:
        return sheets.turnaround, "turnaround"
    return None, ""


def build_prompt(panel: PlannedPanel, direction: DirectedPanel,
                 characters: dict[str, CharacterEntry], style_tags: str = "") -> str:
    present = [characters[n.lower()] for n in panel.characters if n.lower() in characters]
    expression = expression_for(panel.emotion)
    # Series art style (e.g. "heavy shadows, thick lines") right after the base style, so every chapter matches.
    parts = [STYLE_PREFIX, style_tags.strip(", "), SHOT_TAGS[direction.shot], ANGLE_TAGS[direction.angle],
             COUNT_TAGS.get(len(present), "group of people")]
    for character in present:
        # The fixed tags, exactly as written in the bible (+ this panel's expression).
        face = EXPRESSION_TAGS[expression] if direction.shot != "establishing" else ""
        # A trained character LoRA is "summoned" by its trigger word, placed first in the group.
        trigger = f"{character.lora.trigger}, " if character.has_lora() else ""
        parts.append(f"({trigger}{character.tag_prompt()}{', ' + face if face else ''})")
    parts += [panel.action.rstrip("."), f"setting: {panel.setting}", direction.composition.rstrip(".")]
    mood = MOOD_TAGS.get(panel.emotion.lower())
    if mood:
        parts.append(mood)
    parts.append(STYLE_SUFFIX)
    return ", ".join(p for p in parts if p)


def image_size_for_aspect(aspect: float, base: int = 1008, multiple: int = 64,
                          min_side: int = 512, max_side: int = 1536) -> tuple[int, int]:
    """Width/height with the panel's aspect ratio and about base² pixels.

    SDXL works in a latent space 8x smaller than the image and behaves best near its
    training size (~1 megapixel) with sides that are multiples of 64. Capping the long
    side keeps memory use safe on an 8 GB GPU.
    """
    aspect = max(0.25, min(4.0, aspect))
    width = (base * base * aspect) ** 0.5
    height = width / aspect

    def snap(v: float) -> int:
        return max(min_side, min(max_side, int(round(v / multiple)) * multiple))

    return snap(width), snap(height)


def panel_references(panel: PlannedPanel, characters: dict[str, CharacterEntry], job_dir: Path,
                     limit: int = 2) -> tuple[list[Path], list[str]]:
    """Reference images (max 2 — the IP-Adapter workflows support 1 or 2) + labels."""
    paths, labels = [], []
    for name in panel.characters:
        entry = characters.get(name.lower())
        if entry is None:
            continue
        ref, kind = choose_reference(entry, panel.emotion)
        if ref and (job_dir / ref).exists():
            paths.append(job_dir / ref)
            labels.append(f"{entry.name}: {kind}")
        if len(paths) >= limit:
            break
    return paths, labels


__all__ = ["build_prompt", "choose_reference", "expression_for", "image_size_for_aspect", "panel_references",
           "NEGATIVE_PROMPT", "CLOSE_SHOTS"]
