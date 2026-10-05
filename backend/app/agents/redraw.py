"""The quality loop: draw a panel -> score it -> redraw with the Editor's fix -> keep the best.

    attempt 1: generate -> CLIP score -> Editor review -> combined score
        pass?            -> accepted, done
        fail?            -> apply the Editor's fix (prompt / negative / IP-Adapter weight / seed)
    attempt 2, 3: same
    limits hit (EDITOR_MAX_ATTEMPTS, or a job budget: LLM calls, LLM cost, GPU seconds)
                         -> keep the best-scoring attempt, mark the panel "needs_review"

Every attempt (image, prompt, seed, scores, Editor feedback) stays in the job state, so the
timeline can show them side by side. The same loop serves the first pipeline run and the
Phase 4 editor actions (instructions, inpainting), which start a new "round".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from ..providers.base import ImageRequest
from .editor import review_panel
from .graph import Ctx
from .quality import QualityConfig, apply_fix, best_attempt, budget_problem, combine
from .runner import AgentFailed
from .schemas import DirectedPanel, EditorFix, PlannedPanel
from .state import MangaProject, PanelAttempt, PanelPrompt, PanelResult

log = logging.getLogger("manga.redraw")


@dataclass
class DrawSettings:
    """What the next attempt is drawn with (starts from the prompt builder's PanelPrompt)."""

    prompt: str
    negative_prompt: str
    seed: int
    ipadapter_weight: float | None
    fix_applied: EditorFix | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_spec(cls, spec: PanelPrompt) -> "DrawSettings":
        return cls(spec.prompt, spec.negative_prompt, spec.seed, spec.ipadapter_weight)


# Hook for the Phase 4/5 workflows (inpaint, ControlNet...): returns the PIL image + info for one attempt.
Generator = Callable[[DrawSettings, int], tuple[Image.Image, dict[str, Any]]]


def attempt_path(job_dir: Path, page: int, panel: int, attempt: int) -> Path:
    return job_dir / "panels" / f"p{page:02d}_{panel:02d}_a{attempt}.png"


def default_generator(ctx: Ctx, spec: PanelPrompt, planned: PlannedPanel, directed: DirectedPanel) -> Generator:
    def generate(draw: DrawSettings, attempt: int) -> tuple[Image.Image, dict[str, Any]]:
        image = ctx.image.generate(ImageRequest(
            prompt=draw.prompt, negative_prompt=draw.negative_prompt, width=spec.width, height=spec.height,
            seed=draw.seed, kind="panel", reference_images=[ctx.job_dir / r for r in spec.references],
            ipadapter_weight=draw.ipadapter_weight,
            metadata={"page": spec.page, "panel": spec.panel, "shot": directed.shot, "angle": directed.angle,
                      "characters": list(planned.characters), "mood": planned.emotion, "attempt": attempt},
        ))
        info = dict(getattr(ctx.image, "last_info", {}) or {})
        return image, info
    return generate


def score_consistency(p: MangaProject, ctx: Ctx, image: Path, characters: list[str]) -> tuple[dict[str, float], str]:
    from .pipeline import character_references, scorer_for  # late import: pipeline imports this module

    scorer = scorer_for(ctx.settings)
    if scorer is None:
        return {}, "off"
    scores = {}
    for name in characters:
        score = scorer.score(image, character_references(p, name, ctx.job_dir))
        if score is not None:
            scores[name] = round(score, 3)
    return scores, scorer.method


def review_attempt(p: MangaProject, ctx: Ctx, attempt: PanelAttempt, spec: PanelPrompt, planned: PlannedPanel,
                   directed: DirectedPanel, cfg: QualityConfig) -> None:
    """Ask the Editor (unless disabled / out of budget) and compute the combined quality score."""
    if not ctx.settings.editor_enabled:
        attempt.status, attempt.note = "unreviewed", "Editor disabled (EDITOR_ENABLED=false)"
        return
    problem = budget_problem(p, ctx.settings)
    if problem:
        attempt.status, attempt.note = "unreviewed", problem
        p.budget.exhausted = p.budget.exhausted or problem
        return
    try:
        review, step = review_panel(project=p, spec=spec, planned=planned, directed=directed,
                                    image=ctx.job_dir / attempt.image, job_dir=ctx.job_dir, attempt=attempt.attempt,
                                    prompt=attempt.prompt, consistency=attempt.consistency, llm=ctx.llm,
                                    prices=ctx.prices, seed=attempt.seed)
    except AgentFailed as exc:  # a broken review must not sink the whole manga
        p.add_step(exc.step)
        attempt.status, attempt.note = "unreviewed", f"Editor failed: {exc}"
        p.warn("Some panels could not be reviewed by the Editor (see the Quality loop)")
        return
    p.add_step(step)
    attempt.review = review
    # Only real CLIP similarities vote: the "simple" pixel fallback measures layout, not likeness.
    clip = attempt.consistency if attempt.consistency_method == "clip" else {}
    attempt.quality = combine(review, clip, cfg)


def run_quality_loop(p: MangaProject, ctx: Ctx, spec: PanelPrompt, planned: PlannedPanel, directed: DirectedPanel,
                     *, start: DrawSettings | None = None, source: str = "auto", generator: Generator | None = None,
                     max_attempts: int | None = None, seed_locked: bool = False,
                     progress: Callable[[str], None] | None = None) -> PanelResult:
    """Draw (or redraw) one panel until it passes, a limit is hit, or attempts run out."""
    key = (spec.page, spec.panel)
    cfg = QualityConfig.from_settings(ctx.settings)
    generator = generator or default_generator(ctx, spec, planned, directed)
    max_attempts = max_attempts or ctx.settings.editor_max_attempts
    say = progress or (lambda message: None)
    (ctx.job_dir / "panels").mkdir(parents=True, exist_ok=True)

    result = p.panel_result(*key)
    if result is None:
        result = PanelResult(page=spec.page, panel=spec.panel, image="")
        p.panels.append(result)
    round_no = (max((a.round for a in result.attempts), default=0) + 1) if result.attempts else 1
    result.status = "drawing"  # resume knows this panel isn't finished
    draw = start or DrawSettings.from_spec(spec)
    this_round: list[PanelAttempt] = []
    stop_reason = ""

    for index in range(max_attempts):
        number = len(result.attempts) + 1
        say(f"page {spec.page} panel {spec.panel}: drawing attempt {index + 1}")
        started = time.monotonic()
        image, info = generator(draw, number)
        seconds = round(time.monotonic() - started, 2)
        path = attempt_path(ctx.job_dir, spec.page, spec.panel, number)
        image.save(path)
        p.budget.gpu_seconds = round(p.budget.gpu_seconds + seconds, 2)
        p.budget.images += 1

        attempt = PanelAttempt(
            attempt=number, round=round_no, source=source if index == 0 else "redraw",
            image=path.relative_to(ctx.job_dir).as_posix(), prompt=draw.prompt, negative_prompt=draw.negative_prompt,
            seed=draw.seed, width=spec.width, height=spec.height, ipadapter_weight=draw.ipadapter_weight,
            workflow=info.pop("workflow", ctx.image.name), seconds=seconds, fix_applied=draw.fix_applied,
            note="; ".join(draw.notes), extra=info,
        )
        attempt.consistency, attempt.consistency_method = score_consistency(p, ctx, path, list(planned.characters))
        result.attempts.append(attempt)
        this_round.append(attempt)

        say(f"page {spec.page} panel {spec.panel}: Editor reviewing attempt {index + 1}")
        review_attempt(p, ctx, attempt, spec, planned, directed, cfg)
        p.save(ctx.job_dir)  # every attempt survives a crash

        if attempt.quality and attempt.quality.passed:
            break
        if attempt.review is None:          # unreviewed (disabled / budget / Editor error): nothing to fix
            stop_reason = attempt.note
            break
        if index == max_attempts - 1:
            stop_reason = f"still failing after {max_attempts} attempts"
            break
        problem = budget_problem(p, ctx.settings)
        if problem:
            p.budget.exhausted = p.budget.exhausted or problem
            stop_reason = problem
            break
        attempt.status = "rejected"
        fix = attempt.review.fix
        redraw = apply_fix(draw.prompt, draw.negative_prompt, draw.seed, draw.ipadapter_weight, fix,
                           attempt=number, seed_locked=seed_locked)
        draw = DrawSettings(redraw.prompt, redraw.negative_prompt, redraw.seed, redraw.ipadapter_weight,
                            fix_applied=fix, notes=redraw.notes)
        p.budget.redraws += 1
        log.info("redraw p%d·%d attempt %d: %s", spec.page, spec.panel, number + 1, redraw.notes)

    best = best_attempt(this_round)
    for attempt in this_round:
        if attempt is best:
            if attempt.quality and attempt.quality.passed:
                attempt.status = "accepted"
            elif attempt.review is None:
                attempt.status = "unreviewed"
            else:
                attempt.status = "needs_review"
        elif attempt.status in ("pending", "unreviewed"):
            attempt.status = "rejected"
    result.use_attempt(best)
    result.status = {"accepted": "accepted", "needs_review": "needs_review"}.get(best.status, "unreviewed")
    result.review_note = "" if result.status == "accepted" else (
        f"Kept attempt {best.attempt} (best score): {stop_reason}" if stop_reason else "")
    p.save(ctx.job_dir)
    return result


__all__ = ["run_quality_loop", "DrawSettings", "attempt_path", "score_consistency"]
