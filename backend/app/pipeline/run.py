"""Pipeline orchestrator: runs all five stages for one story and writes a job folder.

Output folder layout:
    script.json                 validated manga script
    characters/<name>.png       reference images  (+ sheets.json)
    panels/p01_01.png ...       raw panel art     (+ prompts.json)
    pages/rtl/page_01.png ...   lettered pages, right-to-left reading order
    pages/ltr/page_01.png ...   lettered pages, left-to-right reading order
    manga_rtl.pdf, manga_ltr.pdf
    result.json                 manifest of everything above
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..providers import get_image_provider, get_llm_provider
from ..providers.base import ImageProvider, LLMProvider
from .characters import build_character_sheets, stable_seed
from .export import export_pdf, export_pngs
from .layout import LayoutConfig, compose_page, panel_aspects
from .panels import generate_panel_images
from .script import generate_script

STAGES = ["script", "characters", "panels", "layout", "export"]
DIRECTIONS = ["rtl", "ltr"]

# progress(stage, fraction 0..1, message)
ProgressFn = Callable[[str, float, str], None]


def run_pipeline(
    story: str,
    *,
    settings: Settings,
    out_dir: Path,
    llm: LLMProvider | None = None,
    image: ImageProvider | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Run story -> pages. Returns the manifest (also saved as result.json)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    llm = llm or get_llm_provider(settings)
    image = image or get_image_provider(settings)
    report = progress or (lambda stage, fraction, message: None)
    rel = lambda p: Path(p).relative_to(out_dir).as_posix()  # noqa: E731

    # 1. Story -> script
    report("script", 0.0, f"Writing script with {llm.name} LLM")
    script, warnings = generate_script(
        story, llm, panels_per_page=4, max_pages=settings.max_pages,
        on_attempt=lambda n: report("script", 0.1, f"LLM attempt {n}"),
    )
    (out_dir / "script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    report("script", 1.0, f"{len(script.pages)} page(s), {len(script.all_panels())} panels")

    # 2. Character sheets
    report("characters", 0.0, "Creating character sheets")
    sheets = build_character_sheets(
        script, image, out_dir, reference_size=min(768, settings.image_base_size),
        on_progress=lambda done, total, name: report("characters", done / max(total, 1), f"Drew {name}"),
    )
    report("characters", 1.0, f"{len(sheets)} character(s)")

    # 3. Panel images (generated in the shape of their layout slot)
    layout_cfg = LayoutConfig(font_path=settings.lettering_font)
    report("panels", 0.0, f"Drawing panels with {image.name} image model")
    panel_files = generate_panel_images(
        script, sheets, image, out_dir,
        aspects=panel_aspects(script, layout_cfg), job_seed=stable_seed(story),
        base_size=settings.image_base_size,
        on_progress=lambda done, total, msg: report("panels", done / max(total, 1), f"Drew {msg}"),
    )

    # 4. Layout + lettering, in both reading directions (cheap: no AI involved)
    report("layout", 0.0, "Laying out pages and lettering")
    pages: dict[str, list] = {d: [] for d in DIRECTIONS}
    page_info: dict[str, list] = {d: [] for d in DIRECTIONS}
    steps = len(DIRECTIONS) * len(script.pages)
    done = 0
    for direction in DIRECTIONS:
        for page in script.pages:
            images = {key[1]: path for key, path in panel_files.items() if key[0] == page.page_number}
            img, info = compose_page(page, images, layout_cfg, rtl=(direction == "rtl"), title=script.title)
            pages[direction].append(img)
            page_info[direction].append(info)
            done += 1
            report("layout", done / steps, f"Page {page.page_number} ({direction.upper()})")

    # 5. Export
    report("export", 0.0, "Exporting PNG and PDF")
    outputs = {}
    for direction in DIRECTIONS:
        pngs = export_pngs(pages[direction], out_dir / "pages" / direction)
        pdf = export_pdf(pages[direction], out_dir / f"manga_{direction}.pdf")
        outputs[direction] = {"pages": [rel(p) for p in pngs], "pdf": rel(pdf),
                              "layout": page_info[direction]}
    manifest = {
        "title": script.title,
        "page_count": len(script.pages),
        "panel_count": len(script.all_panels()),
        "providers": {"llm": llm.name, "image": image.name},
        "warnings": warnings,
        "script": "script.json",
        "prompts": "panels/prompts.json",
        "characters": [{"name": s.name, "description": s.prompt_description,
                        "reference_image": s.reference_image} for s in sheets],
        "outputs": outputs,
    }
    (out_dir / "result.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report("export", 1.0, "Done")
    return manifest
