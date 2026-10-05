"""Panel Revision agent — turn a plain-language instruction into a new panel spec, then redraw.

    "make her angrier"     -> emotion "furious", + "clenched teeth, glaring", same seed
    "camera from below"    -> angle "low", + "from below", new seed (the composition changes)

The LLM only rewrites the *spec* (action, emotion, shot, angle, composition, extra tags). Plain
code rebuilds the image prompt from it with the same prompt builder as the first drawing (so the
character's fixed bible tags and the matching reference image are kept), and the panel goes
through the normal quality loop: draw -> Editor review -> redraw with fixes.
"""

from __future__ import annotations

import json

from .graph import Ctx
from .prompt_builder import build_prompt, panel_references
from .quality import apply_negative_fix, apply_prompt_fix, next_seed
from .redraw import DrawSettings, run_quality_loop
from .runner import AgentStep, run_agent
from .schemas import DirectedPanel, EditorFix, PanelRevision, PlannedPanel
from .state import MangaProject, PanelPrompt, PanelResult

SYSTEM = """You are the director of a black-and-white manga, revising ONE panel after a note from the author.

You get the panel's current spec (action, emotion, shot, angle, composition), the characters in it and the
author's instruction. Return the updated spec:
- Change only what the instruction asks for; keep everything else (same characters, same setting, same moment).
- shot: extreme close-up, close-up, medium, wide, establishing, over-the-shoulder.
  angle: eye level, low (camera below, looking up), high (camera above), bird's eye.
- prompt_add: short booru-style image tags that express the change ("clenched teeth", "glaring",
  "from below", "tears", "rain"). prompt_remove: current tags that contradict it. negative_add: things to avoid.
- keep_seed: true for small changes (expression, a detail), false when framing or camera changes.
- Never add text or speech bubbles to the image. Original characters only.
- summary: one sentence describing the change.
- Answer with JSON only, matching the schema."""


def revise_spec(project: MangaProject, planned: PlannedPanel, directed: DirectedPanel, spec: PanelPrompt,
                instruction: str, llm, prices=(None, None)) -> tuple[PanelRevision, AgentStep]:
    characters = [{"name": n, "fixed_look": (project.character(n).tag_prompt() if project.character(n) else "")}
                  for n in planned.characters]
    current = {"action": planned.action, "emotion": planned.emotion, "setting": planned.setting,
               "shot": directed.shot, "angle": directed.angle, "composition": directed.composition,
               "characters": characters, "image_prompt": spec.prompt}
    user = (f"<panel>\n{json.dumps(current, indent=1)}\n</panel>\n\n"
            f"<instruction>\n{instruction.strip()}\n</instruction>")
    return run_agent(
        agent="panel_revision", label=f"Panel revision p{spec.page}·{spec.panel}", llm=llm, system=SYSTEM,
        user=user, output_model=PanelRevision, task="panel_revision",
        context={**current, "instruction": instruction},
        inputs_summary={"panel": f"p{spec.page}·{spec.panel}", "instruction": instruction}, prices=prices,
    )


def apply_revision(project: MangaProject, planned: PlannedPanel, directed: DirectedPanel, spec: PanelPrompt,
                   revision: PanelRevision, job_dir, *, attempt_hint: int) -> DrawSettings:
    """Update the stored spec (page plan, director plan, prompt) and return what to draw next."""
    planned.action, planned.emotion = revision.action, revision.emotion
    directed.shot, directed.angle, directed.composition = revision.shot, revision.angle, revision.composition
    characters = {c.name.lower(): c for c in project.characters}
    fix = EditorFix(prompt_add=revision.prompt_add, prompt_remove=revision.prompt_remove,
                    negative_add=revision.negative_add)
    # Same prompt builder as the first drawing -> fixed character tags + matching expression reference.
    prompt = apply_prompt_fix(build_prompt(planned, directed, characters), fix)
    negative = apply_negative_fix(spec.negative_prompt, fix)
    refs, labels = panel_references(planned, characters, job_dir)
    spec.prompt, spec.negative_prompt = prompt, negative
    spec.references = [r.relative_to(job_dir).as_posix() for r in refs]
    spec.reference_kinds = labels
    if not revision.keep_seed:
        spec.seed = next_seed(spec.seed, attempt_hint)
    return DrawSettings(prompt=prompt, negative_prompt=negative, seed=spec.seed,
                        ipadapter_weight=spec.ipadapter_weight if refs else None,
                        notes=[f"instruction: {revision.summary}"])


def find_panel(project: MangaProject, page: int, panel: int) -> tuple[PlannedPanel, DirectedPanel, PanelPrompt]:
    assert project.page_plan and project.director
    planned = next(p for p in project.page_plan.pages[page - 1].panels if p.panel_number == panel)
    directed = next(p for p in project.director.pages[page - 1].panels if p.panel_number == panel)
    spec = next(s for s in project.prompts if (s.page, s.panel) == (page, panel))
    return planned, directed, spec


def revise_panel(project: MangaProject, ctx: Ctx, page: int, panel: int, instruction: str,
                 seed_locked: bool = False) -> PanelResult:
    """The whole action: revision agent -> updated spec -> quality loop (new round)."""
    planned, directed, spec = find_panel(project, page, panel)
    ctx.progress("panels", 0.05, f"Panel Revision agent: '{instruction}'")
    revision, step = revise_spec(project, planned, directed, spec, instruction, ctx.llm, ctx.prices)
    project.add_step(step)
    result = project.panel_result(page, panel)
    start = apply_revision(project, planned, directed, spec, revision, ctx.job_dir,
                           attempt_hint=len(result.attempts) + 1 if result else 1)
    chosen = result.attempt(result.chosen_attempt) if result else None
    if seed_locked and chosen:
        start.seed = spec.seed = chosen.seed   # locked: keep the current composition
    project.save(ctx.job_dir)
    return run_quality_loop(project, ctx, spec, planned, directed, start=start, source="revision",
                            seed_locked=seed_locked, progress=lambda m: ctx.progress("panels", 0.5, m))


__all__ = ["revise_panel", "revise_spec", "apply_revision", "find_panel"]
