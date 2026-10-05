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


# ----------------------------------------------------------------------------- Phase 5 exports
def comic_info(title: str, pages: int, rtl: bool, series: str = "", number: int = 1, summary: str = "") -> str:
    """ComicInfo.xml: the metadata file comic readers (CDisplayEx, YACReader, Komga, Kavita...) read
    from a CBZ. Manga="YesAndRightToLeft" makes them page right to left."""
    from xml.sax.saxutils import escape
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ComicInfo>\n"
            f"  <Title>{escape(title)}</Title>\n  <Series>{escape(series or title)}</Series>\n"
            f"  <Number>{number}</Number>\n  <PageCount>{pages}</PageCount>\n"
            f"  <Summary>{escape(summary)}</Summary>\n"
            f"  <Manga>{'YesAndRightToLeft' if rtl else 'No'}</Manga>\n  <BlackAndWhite>Yes</BlackAndWhite>\n"
            "  <Writer>Story to Manga (AI agents)</Writer>\n</ComicInfo>\n")


def export_cbz(page_files: list[Path], path: Path, *, title: str, rtl: bool, series: str = "", number: int = 1,
               summary: str = "") -> Path:
    """CBZ = a ZIP of the page images in order (+ ComicInfo.xml). Images are stored, not re-compressed."""
    import zipfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        for index, page in enumerate(page_files, start=1):
            zf.write(page, f"{index:03d}{page.suffix}")
        zf.writestr("ComicInfo.xml", comic_info(title, len(page_files), rtl, series, number, summary))
    return path


def export_webtoon(pages: list[Path], layouts: list[dict], out_dir: Path, *, width: int = 800, gap: int = 60,
                   margin: int = 40, max_height: int = 4000) -> list[Path]:
    """Vertical-scroll webtoon: every lettered panel cut from the rendered pages (in reading order),
    scaled to the same width and stacked with white space between them, then cut into slices of at
    most `max_height` px (webtoon platforms want tall images in parts)."""
    strips: list[Image.Image] = []
    for page_path, layout in zip(pages, layouts):
        with Image.open(page_path) as page:
            for panel in layout.get("panels", []):
                r = panel["rect"]
                crop = page.crop((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"])).convert("L")
                inner = width - 2 * margin
                strips.append(crop.resize((inner, max(1, round(crop.height * inner / crop.width))), Image.Resampling.LANCZOS))
    if not strips:
        raise ValueError("No panels to export")
    total = margin + sum(s.height + gap for s in strips) - gap + margin
    full = Image.new("L", (width, total), 255)
    y = margin
    for strip in strips:
        full.paste(strip, (margin, y))
        y += strip.height + gap
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("webtoon_*.png"):
        old.unlink()
    # Cut between panels where possible: walk the strip boundaries.
    cuts, top, y = [], 0, margin
    for strip in strips:
        bottom = y + strip.height
        if bottom - top > max_height and y - gap // 2 > top:
            cuts.append((top, y - gap // 2))
            top = y - gap // 2
        y = bottom + gap
    cuts.append((top, total))
    paths = []
    for index, (a, b) in enumerate(cuts, start=1):
        for start in range(a, b, max_height):                     # a single panel taller than max_height
            part = full.crop((0, start, width, min(b, start + max_height)))
            path = out_dir / f"webtoon_{len(paths) + 1:02d}.png"
            part.save(path, optimize=True)
            paths.append(path)
    return paths
