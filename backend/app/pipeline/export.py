"""Stage 5 — Export finished pages as PNG files and one combined PDF."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def export_pngs(pages: list[Image.Image], out_dir: Path, prefix: str = "page") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for number, page in enumerate(pages, start=1):
        path = out_dir / f"{prefix}_{number:02d}.png"
        page.save(path, optimize=True)
        paths.append(path)
    return paths


def export_pdf(pages: list[Image.Image], path: Path, dpi: int = 150) -> Path:
    """One PDF page per manga page. `dpi` sets the printed size (1240px @150dpi = A4 width)."""
    if not pages:
        raise ValueError("No pages to export")
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = [p.convert("RGB") for p in pages]
    rgb[0].save(path, "PDF", save_all=True, append_images=rgb[1:], resolution=dpi)
    return path
