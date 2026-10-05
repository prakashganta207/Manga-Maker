"""Quality rules for the Editor loop: scoring, pass/fail, budgets, best attempt, applying fixes.

How a panel is judged (all numbers are configurable in .env):

1. The **Editor** (a vision LLM) grades 9 criteria from 1 to 5. We turn that into one number
   between 0 and 1:  editor = mean((score - 1) / 4).  All 4s -> 0.75, all 5s -> 1.0.
2. The **CLIP consistency score** (Phase 2) compares the panel with each character's reference
   images. Raw CLIP similarities live in a narrow band (~0.6 = unrelated, ~0.9 = same look), so we
   stretch that band to 0..1:  clip = (similarity - CLIP_SCORE_LOW) / (CLIP_SCORE_HIGH - CLIP_SCORE_LOW),
   using the *weakest* character in the panel (one drifted character is enough to fail).
3. combined = QUALITY_EDITOR_WEIGHT * editor + (1 - QUALITY_EDITOR_WEIGHT) * clip
   (just the Editor score when the panel has no characters / no CLIP score).
4. The panel **passes** when all three hold:
   - combined >= QUALITY_THRESHOLD (default 0.65 ≈ "mostly 4s with a decent likeness"),
   - no single criterion is at or below QUALITY_MIN_CRITERION (default 2 = "clearly wrong"),
     because a great average can hide one deal-breaker such as a six-fingered hand,
   - the Editor's own verdict is "pass".

Two independent signals are combined because each one fails differently: the LLM can miss small
likeness drift that CLIP notices, and CLIP can't tell a broken hand or a wrong camera angle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import Settings
from .schemas import EDITOR_CRITERIA, EditorFix, EditorReview
from .state import MangaProject, PanelAttempt, QualityScore


@dataclass
class QualityConfig:
    threshold: float = 0.65
    editor_weight: float = 0.7
    min_criterion: int = 2
    clip_low: float = 0.60
    clip_high: float = 0.90

    @classmethod
    def from_settings(cls, settings: Settings) -> "QualityConfig":
        return cls(threshold=settings.quality_threshold, editor_weight=settings.quality_editor_weight,
                   min_criterion=settings.quality_min_criterion, clip_low=settings.clip_score_low,
                   clip_high=settings.clip_score_high)


def editor_score(review: EditorReview) -> float:
    scores = review.scores.as_dict().values()
    return round(sum((s - 1) / 4 for s in scores) / len(EDITOR_CRITERIA), 4)


def clip_score(consistency: dict[str, float], cfg: QualityConfig) -> float | None:
    if not consistency:
        return None
    span = max(1e-6, cfg.clip_high - cfg.clip_low)
    weakest = min(consistency.values())
    return round(max(0.0, min(1.0, (weakest - cfg.clip_low) / span)), 4)


def combine(review: EditorReview | None, consistency: dict[str, float], cfg: QualityConfig) -> QualityScore:
    """Fold the Editor review and the CLIP scores into one pass/fail decision."""
    editor = editor_score(review) if review else None
    clip = clip_score(consistency, cfg)
    if editor is not None and clip is not None:
        combined = cfg.editor_weight * editor + (1 - cfg.editor_weight) * clip
    else:
        combined = editor if editor is not None else (clip if clip is not None else 0.0)
    combined = round(combined, 4)

    reasons: list[str] = []
    if review is None:
        reasons.append("not reviewed by the Editor")
    else:
        if review.verdict != "pass":
            reasons.append("Editor verdict: fail")
        low = [k for k, v in review.scores.as_dict().items() if v <= cfg.min_criterion]
        if low:
            reasons.append(f"criterion at or below {cfg.min_criterion}: {', '.join(low)}")
    if combined < cfg.threshold:
        reasons.append(f"combined score {combined:.2f} < threshold {cfg.threshold:.2f}")
    return QualityScore(editor=editor, clip=clip, combined=combined, threshold=cfg.threshold,
                        passed=not reasons, reasons=reasons)


def best_attempt(attempts: list[PanelAttempt]) -> PanelAttempt:
    """The attempt to keep: passed first, then highest combined score, then fewer listed
    problems, then the most recent (it has the most fixes applied)."""
    if not attempts:
        raise ValueError("no attempts")

    def key(a: PanelAttempt) -> tuple:
        q = a.quality
        problems = len(a.review.problems) if a.review else 99
        return (bool(q and q.passed), q.combined if q else -1.0, -problems, a.attempt)

    return max(attempts, key=key)


# ----------------------------------------------------------------------------- budgets
def budget_problem(project: MangaProject, settings: Settings) -> str | None:
    """Which per-job budget is used up (None = there is room for another redraw)."""
    b = project.budget
    if settings.job_max_llm_calls and b.llm_calls >= settings.job_max_llm_calls:
        return f"LLM call budget used up ({b.llm_calls}/{settings.job_max_llm_calls} calls)"
    if settings.job_max_llm_cost_usd and project.usage.cost_usd >= settings.job_max_llm_cost_usd:
        return f"LLM cost budget used up (${project.usage.cost_usd:.2f}/${settings.job_max_llm_cost_usd:.2f})"
    if settings.job_max_gpu_seconds and b.gpu_seconds >= settings.job_max_gpu_seconds:
        return f"GPU time budget used up ({b.gpu_seconds:.0f}/{settings.job_max_gpu_seconds:.0f} s)"
    return None


# ----------------------------------------------------------------------------- applying fixes
def split_tags(prompt: str) -> list[str]:
    """Split a prompt on top-level commas. "(short hair, red eyes)" stays one tag, because
    the character groups in our prompts are wrapped in parentheses."""
    tags, depth, current = [], 0, ""
    for ch in prompt:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            tags.append(current.strip())
            current = ""
        else:
            current += ch
    tags.append(current.strip())
    return [t for t in tags if t]


def _plain(tag: str) -> str:
    """'(from below:1.2)' -> 'from below' (for comparisons)."""
    return re.sub(r":[0-9.]+\)$", "", tag.strip()).strip("() ").lower()


EMPHASIS = 1.15  # "(tag:1.15)" = ComfyUI prompt weighting: 15% more attention on the fixed tags


def _is_character_group(tag: str) -> bool:
    """'(short black hair, school uniform, smile)' = a character's fixed bible tags."""
    return tag.startswith("(") and not re.search(r":[0-9.]+\)$", tag)


def apply_prompt_fix(prompt: str, fix: EditorFix) -> str:
    tags = split_tags(prompt)
    remove = {r.lower() for r in fix.prompt_remove}
    # Never remove a character group: those are the fixed bible tags (the consistency rule).
    tags = [t for t in tags if _is_character_group(t) or _plain(t) not in remove]
    present = {_plain(t) for t in tags}
    added = [f"({t}:{EMPHASIS})" for t in fix.prompt_add if t.lower() not in present]
    if added:
        # Earlier tags weigh more: put the fixes right after the character groups (before the action).
        groups = [i for i, t in enumerate(tags) if _is_character_group(t)]
        at = (groups[-1] + 1) if groups else min(len(tags), 5)
        tags = tags[:at] + added + tags[at:]
    return ", ".join(tags)


def apply_negative_fix(negative: str, fix: EditorFix) -> str:
    tags = split_tags(negative)
    present = {_plain(t) for t in tags}
    return ", ".join(tags + [t for t in fix.negative_add if t.lower() not in present])


def next_seed(seed: int, attempt: int) -> int:
    # A different but reproducible starting noise for each redraw.
    return (seed + 104729 * attempt) % (2**32)


@dataclass
class RedrawSpec:
    prompt: str
    negative_prompt: str
    seed: int
    ipadapter_weight: float | None
    notes: list[str]


def apply_fix(prompt: str, negative: str, seed: int, weight: float | None, fix: EditorFix, attempt: int,
              *, seed_locked: bool = False) -> RedrawSpec:
    """Turn the Editor's suggested fix into the next attempt's generation settings."""
    notes = []
    new_prompt = apply_prompt_fix(prompt, fix)
    if new_prompt != prompt:
        notes.append(f"prompt: +{fix.prompt_add or []} -{fix.prompt_remove or []}")
    new_negative = apply_negative_fix(negative, fix)
    if new_negative != negative:
        notes.append(f"negative: +{fix.negative_add}")
    new_weight = weight
    if fix.ipadapter_weight is not None and weight is not None:
        # Clamp: below 0.3 the reference barely matters, above 1.0 it copies the reference pose.
        new_weight = round(max(0.3, min(1.0, fix.ipadapter_weight)), 3)
        if new_weight != weight:
            notes.append(f"IP-Adapter weight {weight} -> {new_weight}")
    changed = new_prompt != prompt or new_negative != negative or new_weight != weight
    new = seed
    if not seed_locked and (fix.new_seed or not changed):
        new = next_seed(seed, attempt)  # nothing else changed -> a new seed is the only lever left
        notes.append(f"new seed {new}")
    return RedrawSpec(new_prompt, new_negative, new, new_weight, notes)
