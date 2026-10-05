"""All pipeline nodes, wired into the LangGraph graph.

    writer_beats → writer_pages → director → character_designer → reference_sheets
      → [cast approved?] → prompts → panels → consistency → layout → export

The graph pauses after reference_sheets until every main character is approved (or the
job is auto-approved); approving the cast re-queues the job and it resumes from disk.

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
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..pipeline import templates
from ..pipeline.export import export_pdf
from ..pipeline.bubbles import plan_lettering
from ..pipeline.layout import LayoutConfig, compose_page, plan_page
from ..providers import get_image_provider, get_llm_provider
from ..providers.base import ImageProvider, ImageRequest, LLMProvider
from ..vision.consistency import Scorer, get_scorer
from .cast_store import CastStore
from .character_designer import design_characters
from .director import direct
from .graph import Ctx, Node, run_graph
from .history import record_lettering
from .prompt_builder import NEGATIVE_PROMPT, build_prompt, image_size_for_aspect, panel_references
from .redraw import run_quality_loop
from .schemas import DirectedPanel, PlannedPanel
from .sheets import generate_sheets, sheets_present
from .runner import AgentStep
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


def main_characters(p: MangaProject) -> list:
    names = {n.lower() for n in p.main_character_names()}
    return [c for c in p.characters if c.name.lower() in names]


def node_reference_sheets(p: MangaProject, ctx: Ctx) -> None:
    todo = [c for c in main_characters(p) if not sheets_present(c, ctx.job_dir)]
    for index, character in enumerate(todo, start=1):
        ctx.progress("sheets", (index - 1) / len(todo), f"Drawing {character.name}'s turnaround + expressions")
        started = time.monotonic()
        generate_sheets(character, ctx.image, ctx.job_dir)
        p.budget.gpu_seconds = round(p.budget.gpu_seconds + time.monotonic() - started, 2)
        p.budget.images += 2
        p.save(ctx.job_dir)
    ctx.image.free_memory()  # unload models before the next stage


def approve_all(p: MangaProject) -> None:
    for character in p.characters:
        character.approved = True
        character.status = "approved"


def node_approval(p: MangaProject, ctx: Ctx) -> None:
    """Human-in-the-loop checkpoint. Auto-approve (unattended runs) approves the whole cast;
    otherwise this node does nothing and the gate after it pauses the graph."""
    if p.auto_approve:
        approve_all(p)
        p.trace.append(AgentStep(agent="studio", label="Cast approval", status="ok",
                                 notes=["Auto-approved (unattended run)"],
                                 output=[c.name for c in p.characters]))
    if p.all_approved():
        CastStore(ctx.settings.output_dir).save(p, ctx.job_dir)  # reusable in later chapters


def cast_approved(p: MangaProject) -> bool:
    return p.all_approved()


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


def panel_specs(p: MangaProject) -> dict[tuple[int, int], tuple[PlannedPanel, DirectedPanel]]:
    assert p.page_plan and p.director
    directed = {(pg.page_number, pn.panel_number): pn for pg in p.director.pages for pn in pg.panels}
    return {(pg.page_number, pn.panel_number): (pn, directed[(pg.page_number, pn.panel_number)])
            for pg, pn in p.page_plan.all_panels()}


def node_panels(p: MangaProject, ctx: Ctx) -> None:
    """Draw every panel through the quality loop (draw -> Editor review -> redraw with fixes)."""
    specs = panel_specs(p)
    total = len(p.prompts)
    p.budget_limits(ctx.settings)
    # Sequential on purpose: one image at a time fits an 8 GB GPU.
    for index, spec in enumerate(p.prompts, start=1):
        key = (spec.page, spec.panel)
        done = p.panel_result(*key)
        if done and (done.status != "drawing" or done.locked) and done.image and (ctx.job_dir / done.image).exists():
            continue  # resumed job: this panel was finished before (locked panels are never redrawn)
        planned, directed = specs[key]
        result = run_quality_loop(
            p, ctx, spec, planned, directed,
            progress=lambda message, i=index: ctx.progress("panels", (i - 1) / total, message))
        verdict = {"accepted": "accepted", "needs_review": "needs review"}.get(result.status, result.status)
        ctx.progress("panels", index / total,
                     f"Page {spec.page} panel {spec.panel}: {verdict} after {len(result.attempts)} attempt(s)")
    for warning in getattr(ctx.image, "warnings", []):
        p.warn(warning)
    if p.budget.exhausted:
        p.warn(f"Budget limit reached: {p.budget.exhausted}. Some panels kept their best attempt without more redraws.")
    ctx.image.free_memory()  # unload models before the next stage


_SCORERS: dict[tuple[str, str], Scorer | None] = {}
_SCORER_LOCK = threading.Lock()


def scorer_for(settings: Settings) -> Scorer | None:
    """Load the consistency scorer once per process (importing CLIP takes ~30 s on Windows)."""
    key = (settings.consistency_scorer, settings.clip_model)
    with _SCORER_LOCK:
        if key not in _SCORERS:
            _SCORERS[key] = get_scorer(*key)
        return _SCORERS[key]


def character_references(p: MangaProject, name: str, job_dir: Path) -> list[Path]:
    entry = p.character(name)
    if entry is None:
        return []
    rels = [*entry.sheets.views.values(), *entry.sheets.expression_refs.values()]
    return [job_dir / r for r in rels if (job_dir / r).exists()]


def node_consistency(p: MangaProject, ctx: Ctx) -> None:
    """Score every panel against the references of the characters in it (CLIP similarity)."""
    scorer = scorer_for(ctx.settings)
    prompts = {(x.page, x.panel): x for x in p.prompts}
    for index, result in enumerate(p.panels, start=1):
        if result.consistency_method:
            continue  # already scored inside the quality loop
        if scorer is None:
            result.consistency, result.consistency_method = {}, "off"
            continue
        scores = {}
        for name in prompts[(result.page, result.panel)].characters:
            score = scorer.score(ctx.job_dir / result.image, character_references(p, name, ctx.job_dir))
            if score is not None:
                scores[name] = round(score, 3)
        result.consistency, result.consistency_method = scores, scorer.method
        ctx.progress("consistency", index / len(p.panels), f"Scored page {result.page} panel {result.panel}")
    if scorer is None:
        p.warn("Consistency scoring is off (CONSISTENCY_SCORER=off)")
    elif scorer.method == "simple":
        p.warn("Consistency scores use the simple pixel fallback (install torch + transformers for CLIP)")


def ensure_lettering(p: MangaProject, settings: Settings) -> None:
    """Plan the editable bubble layers for pages that don't have them yet (edited pages are kept)."""
    assert p.page_plan and p.director
    cfg = layout_config(settings)
    for planned, directed in zip(p.page_plan.pages, p.director.pages):
        if p.page_lettering(planned.page_number) is None:
            inner = [r.inset(cfg.border) for r in plan_page(directed.layout, cfg, rtl=True)]
            p.lettering.append(plan_lettering(planned, inner, font_size=cfg.font_size, font_path=cfg.font_path))
            record_lettering(p, planned.page_number, "auto_place", "Automatic lettering")
    p.lettering.sort(key=lambda pl: pl.page)


def render_pages(p: MangaProject, settings: Settings, job_dir: Path, pages: list[int] | None = None) -> None:
    """(Re-)render lettered pages in both reading directions from the stored layers."""
    assert p.page_plan and p.director
    cfg = layout_config(settings)
    ensure_lettering(p, settings)
    outputs: dict[str, Any] = p.outputs or {}
    for direction in DIRECTIONS:
        out_dir = job_dir / "pages" / direction
        out_dir.mkdir(parents=True, exist_ok=True)
        entry = outputs.setdefault(direction, {"pages": [], "layout": []})
        paths, infos = list(entry.get("pages", [])), list(entry.get("layout", []))
        for index, (planned, directed) in enumerate(zip(p.page_plan.pages, p.director.pages)):
            if pages is not None and planned.page_number not in pages and index < len(paths):
                continue
            images = {r.panel: job_dir / r.image for r in p.panels if r.page == planned.page_number}
            img, info = compose_page(planned, directed.layout, images, cfg, rtl=(direction == "rtl"), title=p.title,
                                     lettering=p.page_lettering(planned.page_number))
            path = out_dir / f"page_{planned.page_number:02d}.png"
            img.save(path, optimize=True)
            rel = path.relative_to(job_dir).as_posix()
            if index < len(paths):
                paths[index], infos[index] = rel, info
            else:
                paths.append(rel)
                infos.append(info)
        entry["pages"], entry["layout"] = paths, infos
    p.outputs = outputs


def export_documents(p: MangaProject, job_dir: Path) -> None:
    from PIL import Image
    for direction in DIRECTIONS:
        out = p.outputs[direction]
        images = [Image.open(job_dir / page) for page in out["pages"]]
        pdf = export_pdf(images, job_dir / f"manga_{direction}.pdf")
        out["pdf"] = pdf.relative_to(job_dir).as_posix()


def node_layout(p: MangaProject, ctx: Ctx) -> None:
    render_pages(p, ctx.settings, ctx.job_dir)


def node_export(p: MangaProject, ctx: Ctx) -> None:
    export_documents(p, ctx.job_dir)
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
        Node("reference_sheets", "sheets", "Reference sheets", node_reference_sheets,
             lambda p: all(sheets_present(c, job_dir) for c in main_characters(p))),
        Node("approval", "approval", "Cast approval", node_approval, cast_approved),
        Node("prompts", "prompts", "Prompt builder", node_prompts, lambda p: bool(p.prompts)),
        Node("panels", "panels", "Drawing panels + Editor loop", node_panels,
             lambda p: bool(p.prompts) and len(p.panels) == len(p.prompts)
             and all(r.status != "drawing" and r.image and (job_dir / r.image).exists() for r in p.panels)),
        Node("consistency", "consistency", "Consistency score", node_consistency,
             lambda p: bool(p.panels) and all(r.consistency_method for r in p.panels)),
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
    extras = dict(extras or {})
    if project.project_id != project.job_id and "cast" not in extras:
        # A new chapter of an earlier project: reuse its approved cast (images included).
        extras["cast"] = CastStore(settings.output_dir).install(project.project_id, job_dir)
    ctx = Ctx(settings=settings, llm=llm, image=image, job_dir=job_dir,
              progress=progress or (lambda s, f, m: None), extras=extras)
    project.save(job_dir)
    try:
        # The conditional edge after "approval" stops the run until the cast is approved.
        project = run_graph(project, build_nodes(job_dir), ctx, gate_after="approval", gate=cast_approved)
    except Exception as exc:
        project.status = "failed"
        project.error = f"{type(exc).__name__}: {exc}"
        project.save(job_dir)
        raise
    if project.status != "done":
        project.status = "awaiting_approval" if not project.all_approved() else project.status
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
        "quality": quality_summary(project),
        "characters": [{"name": c.name, "description": c.description, "tags": c.tag_prompt(),
                        "approved": c.approved, "reference_image": c.sheets.views.get("front") or c.sheets.turnaround}
                       for c in project.characters],
        "outputs": {d: {"pages": o.get("pages", []), "pdf": o.get("pdf")} for d, o in project.outputs.items()},
        "project": "project.json",
    }


def quality_summary(project: MangaProject) -> dict[str, Any]:
    """Counts for the UI + cost per page from the budget counters."""
    statuses = [r.status for r in project.panels]
    pages = len(project.page_plan.pages) if project.page_plan else 0
    return {
        "accepted": statuses.count("accepted"), "needs_review": statuses.count("needs_review"),
        "unreviewed": statuses.count("unreviewed"), "attempts": sum(len(r.attempts) for r in project.panels),
        "redraws": project.budget.redraws, "llm_calls": project.budget.llm_calls,
        "gpu_seconds": project.budget.gpu_seconds, "budget_exhausted": project.budget.exhausted,
        "cost_per_page_usd": round(project.usage.cost_usd / pages, 4) if pages else 0.0,
        "gpu_seconds_per_page": round(project.budget.gpu_seconds / pages, 1) if pages else 0.0,
    }


def templates_catalogue() -> list[dict]:
    return [t.summary() for t in templates.TEMPLATES]


__all__ = ["run_project", "new_project", "manifest", "build_nodes", "templates_catalogue"]
