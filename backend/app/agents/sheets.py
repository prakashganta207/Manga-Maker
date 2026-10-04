"""Character reference sheets: turnaround (front / side / back) + expression sheet.

We ask the image model for ONE wide image with the views side by side, then crop it
into equal columns. Drawing all views in a single image keeps them consistent with each
other (same model "imagination" for that character). The crops become the reference
images that IP-Adapter looks at when drawing panels.

Seeds are stored in the character bible, so a sheet can be redrawn identically — or,
when the user clicks "regenerate", with a new seed for a new variation.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from ..providers.base import ImageProvider, ImageRequest
from .prompt_builder import NEGATIVE_PROMPT
from .state import EXPRESSIONS, VIEWS, CharacterEntry

# SDXL-friendly wide sizes (~1 megapixel, multiples of 64).
TURNAROUND_SIZE = (1216, 832)
EXPRESSION_SIZE = (1536, 640)

SHEET_STYLE = "monochrome, greyscale, manga, clean lineart, flat shading, simple white background, masterpiece"
SHEET_NEGATIVE = NEGATIVE_PROMPT + ", different characters, scenery, background objects, cropped, panel border"


def turnaround_prompt(character: CharacterEntry) -> str:
    return (f"character turnaround sheet, reference sheet, the same character three times side by side, "
            f"front view, side view, back view, full body, standing straight, ({character.tag_prompt()}), "
            f"{character.body_type}, {SHEET_STYLE}")


def expression_prompt(character: CharacterEntry) -> str:
    return (f"expression sheet, five portraits of the same character in a row, head and shoulders, "
            f"{', '.join(EXPRESSIONS)} expressions, ({character.tag_prompt()}), {SHEET_STYLE}")


def autocrop(image: Image.Image, pad: int = 16) -> Image.Image:
    """Trim the white margin around a drawing (keeps a little padding)."""
    grey = image.convert("L")
    diff = ImageChops.difference(grey, Image.new("L", grey.size, 255))
    bbox = ImageChops.add(diff, diff, 2.0, -20).getbbox()  # ignore near-white noise
    if not bbox:
        return image
    left, top, right, bottom = bbox
    return image.crop((max(0, left - pad), max(0, top - pad),
                       min(image.width, right + pad), min(image.height, bottom + pad)))


def split_columns(image: Image.Image, count: int) -> list[Image.Image]:
    width = image.width / count
    return [autocrop(image.crop((round(i * width), 0, round((i + 1) * width), image.height))) for i in range(count)]


def generate_sheets(character: CharacterEntry, provider: ImageProvider, job_dir: Path,
                    which: str = "both") -> None:
    """Draw (or redraw) the sheets and crops for one character, updating the entry in place."""
    folder = job_dir / "characters" / character.slug
    folder.mkdir(parents=True, exist_ok=True)
    rel = lambda p: p.relative_to(job_dir).as_posix()  # noqa: E731
    version = f"v{character.version}"

    if which in ("both", "turnaround"):
        width, height = TURNAROUND_SIZE
        sheet = provider.generate(ImageRequest(
            prompt=turnaround_prompt(character), negative_prompt=SHEET_NEGATIVE, width=width, height=height,
            seed=character.turnaround_seed, kind="turnaround", metadata={"name": character.name}))
        path = folder / f"turnaround_{version}.png"
        sheet.save(path)
        character.sheets.turnaround = rel(path)
        views = {}
        for view, crop in zip(VIEWS, split_columns(sheet, len(VIEWS))):
            crop_path = folder / f"{view}_{version}.png"
            ImageOps.grayscale(crop).save(crop_path)
            views[view] = rel(crop_path)
        character.sheets.views = views

    if which in ("both", "expressions"):
        width, height = EXPRESSION_SIZE
        sheet = provider.generate(ImageRequest(
            prompt=expression_prompt(character), negative_prompt=SHEET_NEGATIVE, width=width, height=height,
            seed=character.expression_seed, kind="expressions",
            metadata={"name": character.name, "expressions": EXPRESSIONS}))
        path = folder / f"expressions_{version}.png"
        sheet.save(path)
        character.sheets.expressions = rel(path)
        refs = {}
        for expression, crop in zip(EXPRESSIONS, split_columns(sheet, len(EXPRESSIONS))):
            crop_path = folder / f"{expression}_{version}.png"
            ImageOps.grayscale(crop).save(crop_path)
            refs[expression] = rel(crop_path)
        character.sheets.expression_refs = refs

    character.status = "approved" if character.approved else "ready"


def sheets_present(character: CharacterEntry, job_dir: Path) -> bool:
    sheets = character.sheets
    files = [sheets.turnaround, sheets.expressions, *sheets.views.values(), *sheets.expression_refs.values()]
    return bool(sheets.turnaround and sheets.expressions) and all(f and (job_dir / f).exists() for f in files)
