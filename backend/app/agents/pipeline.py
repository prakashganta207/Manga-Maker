"""All pipeline nodes, wired into the LangGraph graph.

    writer_beats → writer_pages → director → character_designer → reference_sheets
      → [cast approved?] → prompts → panels → consistency → layout → export

Output folder of a job:
    project.json                 the whole shared state (resume point)
    characters/<slug>/...        turnaround + expression sheets and cropped references
    panels/p01_01.png ...        raw panel art (+ prompts in project.json)
    pages/rtl|ltr/page_01.png    lettered pages
    manga_rtl.pdf, manga_ltr.pdf
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..pipeline import templates
from ..pipeline.export import export_pdf
from ..pipeline.layout import LayoutConfig, compose_page, plan_page
from ..providers import get_image_provider, get_llm_provider
from ..providers.base import ImageProvider, ImageRequest, LLMProvider
from .character_designer import design_characters
from .director import direct
from .graph import Ctx, Node, run_graph
from .prompt_builder import NEGATIVE_PROMPT, build_prompt, image_size_for_aspect, panel_references
from .state import MangaProject, PanelPrompt, PanelResult
from .writer import plan_pages, write_beat_sheet

log = logging.getLogger("manga.pipeline")
DIRECTIONS = ("rtl", "ltr")


def story_seed(story: str) -> int:
    return int(hashlib.sha256(story.encode("utf-8")).hexdigest()[:8], 16)


def panel_seed(story: str, page: int, panel: int) -> int:
    # Different seed per panel (different compositions), reproducible for the same story.
    return (story_seed(story) + page * 1000 + panel) % (2**32)


def layout_config(settings: Settings) -> LayoutConfig:
    return LayoutConfig(font_path=settings.lettering_font)


# --------------------------------------------------------------------------- node bodies
def node_writer_beats(p: MangaProject, ctx: Ctx) -> None:
    p.add_step(write_beat_sheet(p, ctx.llm, ctx.prices))


def node_writer_pages(p: MangaProject, ctx: Ctx) -> None:
    p.add_step(plan_pages(p, ctx.llm, ctx.prices))


def node_director(p: MangaProject, ctx: Ctx) -> None:
    p.add_step(direct(p, ctx.llm, ctx.prices))


def node_character_designer(p: MangaProject, ctx: Ctx) -> None:
    existing = ctx.extras.get("cast") or {}
    p.add_step(design_characters(p, ctx.llm, ctx.prices, existing=existing))


def node_prompts(p: MangaProject, ctx: Ctx) -> None:
    assert p.page_plan and p.director
    cfg = layout_config(ctx.settings)
    characters = {c.name.lower(): c for c in p.characters}
    prompts = []
    for planned, directed in zip(p.page_plan.pages, p.director.pages):
        rects = plan_page(directed.layout, cfg)
        for panel, direction, rect in zip(planned.panels, directed.panels, rects):
            width, height = image_size_for_aspect(rect.w / rect.h, ctx.settings.image_base_size)
            refs, labels = panel_references(panel, characters, ctx.job_dir)
            prompts.append(PanelPrompt(
                page=planned.page_number, panel=panel.panel_number,
                prompt=build_prompt(panel, direction, characters), negative_prompt=NEGATIVE_PROMPT,
                seed=panel_seed(p.story, planned.page_number, panel.panel_number), width=width, height=height,
                characters=list(panel.characters),
                references=[r.relative_to(ctx.job_dir).as_posix() for r in refs], reference_kinds=labels,
                ipadapter_weight=ctx.settings.ipadapter_weight if refs else None,
            ))
    p.prompts = prompts


def node_panels(p: MangaProject, ctx: Ctx) -> None:
    assert p.page_plan and p.director
    panel_dir = ctx.job_dir / "panels"
    panel_dir.mkdir(parents=True, exist_ok=True)
    planned = {(pg.page_number, pn.panel_number): pn for pg, pn in p.page_plan.all_panels()}
    directed = {(pg.page_number, pn.panel_number): pn for pg in p.director.pages for pn in pg.panels}
    total = len(p.prompts)
    # Sequential on purpose: one image at a time fits an 8 GB GPU.
    for index, spec in enumerate(p.prompts, start=1):
        key = (spec.page, spec.panel)
        done = p.panel_result(*key)
        if done and (ctx.job_dir / done.image).exists():
            continue  # resumed job: this panel was drawn before
        panel, direction = planned[key], directed[key]
        started = time.monotonic()
        image = ctx.image.generate(ImageRequest(
            prompt=spec.prompt, negative_prompt=spec.negative_prompt, width=spec.width, height=spec.height,
            seed=spec.seed, kind="panel", reference_images=[ctx.job_dir / r for r in spec.references],
            ipadapter_weight=spec.ipadapter_weight,
            metadata={"page": spec.page, "panel": spec.panel, "shot": direction.shot, "angle": direction.angle,
                      "characters": list(panel.characters), "mood": panel.emotion},
        ))
        path = panel_dir / f"p{spec.page:02d}_{spec.panel:02d}.png"
        image.save(path)
        info = getattr(ctx.image, "last_info", {}) or {}
        p.panels = [r for r in p.panels if (r.page, r.panel) != key]
        p.panels.append(PanelResult(page=spec.page, panel=spec.panel, image=path.relative_to(ctx.job_dir).as_posix(),
                                    seconds=round(time.monotonic() - started, 2), workflow=info.get("workflow", ctx.image.name)))
        p.save(ctx.job_dir)  # progress survives a crash mid-way
        ctx.progress("panels", index / total, f"Drew page {spec.page} panel {spec.panel}")
    for warning in getattr(ctx.image, "warnings", []):
        p.warn(warning)
    ctx.image.free_memory()  # unload models before the next stage


def node_layout(p: MangaProject, ctx: Ctx) -> None:
    assert p.page_plan and p.director
    cfg = layout_config(ctx.settings)
    outputs: dict[str, Any] = {}
    for direction in DIRECTIONS:
        out_dir = ctx.job_dir / "pages" / direction
        out_dir.mkdir(parents=True, exist_ok=True)
        pages, infos = [], []
        for planned, directed in zip(p.page_plan.pages, p.director.pages):
            images = {r.panel: ctx.job_dir / r.image for r in p.panels if r.page == planned.page_number}
            img, info = compose_page(planned, directed.layout, images, cfg, rtl=(direction == "rtl"), title=p.title)
            path = out_dir / f"page_{planned.page_number:02d}.png"
            img.save(path, optimize=True)
            pages.append(path.relative_to(ctx.job_dir).as_posix())
            infos.append(info)
        outputs[direction] = {"pages": pages, "layout": infos}
    p.outputs = outputs


def node_export(p: MangaProject, ctx: Ctx) -> None:
    from PIL import Image
    for direction in DIRECTIONS:
        out = p.outputs[direction]
        images = [Image.open(ctx.job_dir / page) for page in out["pages"]]
        pdf = export_pdf(images, ctx.job_dir / f"manga_{direction}.pdf")
        out["pdf"] = pdf.relative_to(ctx.job_dir).as_posix()
    p.status = "done"


def _exists(p: MangaProject, ctx_dir: Path, rel: str | None) -> bool:
    return bool(rel) and (ctx_dir / rel).exists()


def build_nodes(job_dir: Path) -> list[Node]:
    return [
        Node("writer_beats", "writer", "Writer: beat sheet", node_writer_beats, lambda p: p.beat_sheet is not None),
        Node("writer_pages", "writer", "Writer: page plan", node_writer_pages, lambda p: p.page_plan is not None),
        Node("director", "director", "Director: layouts and shots", node_director, lambda p: p.director is not None),
        Node("character_designer", "characters", "Character Designer: bible", node_character_designer,
             lambda p: bool(p.characters)),
        Node("prompts", "prompts", "Prompt builder", node_prompts, lambda p: bool(p.prompts)),
        Node("panels", "panels", "Drawing panels", node_panels,
             lambda p: bool(p.prompts) and len(p.panels) == len(p.prompts)
             and all((job_dir / r.image).exists() for r in p.panels)),
        Node("layout", "layout", "Layout and lettering", node_layout,
             lambda p: bool(p.outputs) and all(_exists(p, job_dir, pg) for d in DIRECTIONS
                                                for pg in p.outputs.get(d, {}).get("pages", []))),
        Node("export", "export", "Export PNG + PDF", node_export,
             lambda p: p.status == "done" and all(_exists(p, job_dir, p.outputs.get(d, {}).get("pdf"))
                                                  for d in DIRECTIONS)),
    ]


def new_project(story: str, job_id: str, settings: Settings, *, project_id: str | None = None,
                auto_approve: bool | None = None) -> MangaProject:
    return MangaProject(job_id=job_id, project_id=project_id or job_id, story=story.strip(),
                        auto_approve=settings.auto_approve if auto_approve is None else auto_approve,
                        max_pages=settings.max_pages, max_panels_per_page=settings.max_panels_per_page)


def run_project(project: MangaProject, *, settings: Settings, job_dir: Path, llm: LLMProvider | None = None,
                image: ImageProvider | None = None, progress: Callable[[str, float, str], None] | None = None,
                extras: dict | None = None) -> MangaProject:
    """Run (or resume) the agent graph for one project. Returns the updated project."""
    llm = llm or get_llm_provider(settings)
    image = image or get_image_provider(settings)
    project.providers = {"llm": llm.name, "llm_model": getattr(llm, "model", ""), "image": image.name}
    project.status = "running"
    project.error = None
    ctx = Ctx(settings=settings, llm=llm, image=image, job_dir=job_dir,
              progress=progress or (lambda s, f, m: None), extras=extras or {})
    project.save(job_dir)
    try:
        project = run_graph(project, build_nodes(job_dir), ctx)
    except Exception as exc:
        project.status = "failed"
        project.error = f"{type(exc).__name__}: {exc}"
        project.save(job_dir)
        raise
    project.save(job_dir)
    return project


def manifest(project: MangaProject) -> dict[str, Any]:
    """Short summary used by the job API and the reader."""
    return {
        "title": project.title,
        "status": project.status,
        "page_count": len(project.page_plan.pages) if project.page_plan else 0,
        "panel_count": len(project.prompts),
        "providers": project.providers,
        "warnings": project.warnings,
        "usage": project.usage.model_dump(),
        "characters": [{"name": c.name, "description": c.description, "tags": c.tag_prompt(),
                        "approved": c.approved, "reference_image": c.sheets.views.get("front") or c.sheets.turnaround}
                       for c in project.characters],
        "outputs": {d: {"pages": o.get("pages", []), "pdf": o.get("pdf")} for d, o in project.outputs.items()},
        "project": "project.json",
    }


def templates_catalogue() -> list[dict]:
    return [t.summary() for t in templates.TEMPLATES]


__all__ = ["run_project", "new_project", "manifest", "build_nodes", "templates_catalogue"]
