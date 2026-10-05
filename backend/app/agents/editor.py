"""Editor agent — a vision LLM that reviews every finished panel.

How "vision-model evaluation" works here: modern LLMs (Claude, Gemini, GPT-4o...) can look at
images. We send the panel picture plus the character reference images (the same ones IP-Adapter
used), and the Director's spec as text, and ask for a strict JSON grade sheet (`EditorReview`):
nine 1-5 scores, pass/fail, the specific problems it sees, and a *machine-applicable* fix
(prompt tags to add/remove, negative-prompt additions, IP-Adapter weight, new seed).

The LLM grades; plain code decides (agents/quality.py combines the grades with the CLIP score
against a configurable threshold) and applies the fix for the redraw.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..providers.base import ImageInput, LLMProvider
from .runner import AgentStep, run_agent
from .schemas import EDITOR_CRITERIA, DirectedPanel, EditorReview, PlannedPanel
from .state import MangaProject, PanelPrompt

SYSTEM = """You are the senior editor of a black-and-white manga studio. You review ONE finished panel
image against the director's spec and the character reference images, and decide if it can be printed.

Image 1 is the panel. Any further images are character reference sheets (crops) showing how each
character must look.

Score each criterion from 1 to 5 (5 perfect, 4 good, 3 acceptable with flaws, 2 clearly wrong, 1 completely wrong):
{criteria}

Rules:
- Judge only what you can see. Speech bubbles are added later in code, so the panel must NOT contain
  text or bubbles; it SHOULD leave calm space for them.
- verdict "pass" if the panel is good enough to print (no criterion below 3), else "fail".
- problems: specific and visual ("the girl has short hair but the reference shows twin tails", "left hand
  has six fingers"), at most 8. Empty list only when everything is fine.
- fix: concrete changes for the next attempt, in the image model's language (short booru-style tags):
  prompt_add (tags that would fix it, e.g. "from below", "clenched fists", "twin tails"), prompt_remove
  (tags in the current prompt that caused the problem), negative_add (e.g. "extra fingers", "color",
  "text"), ipadapter_weight (raise to 0.8-0.9 if a character looks wrong, lower to 0.5-0.6 if every
  panel copies the reference pose; null to keep), new_seed (true for anatomy problems or a bad
  composition). A failing review MUST include at least one change.
- reasoning: 2-4 sentences.
- Answer with JSON only, matching the schema."""


def system_prompt() -> str:
    criteria = "\n".join(f"- {name}: {text}" for name, text in EDITOR_CRITERIA.items())
    return SYSTEM.format(criteria=criteria)


def review_images(job_dir: Path, image: Path, spec: PanelPrompt, limit: int = 2) -> list[ImageInput]:
    """The panel first, then up to `limit` character references (the ones IP-Adapter used)."""
    images = [ImageInput(image, "the panel to review")]
    for rel, kind in list(zip(spec.references, spec.reference_kinds))[:limit]:
        path = job_dir / rel
        if path.exists():
            images.append(ImageInput(path, f"reference for {kind}"))
    return images


def review_panel(*, project: MangaProject, spec: PanelPrompt, planned: PlannedPanel, directed: DirectedPanel,
                 image: Path, job_dir: Path, attempt: int, prompt: str, consistency: dict[str, float],
                 llm: LLMProvider, prices=(None, None), seed: int | None = None) -> tuple[EditorReview, AgentStep]:
    characters = []
    for name in planned.characters:
        entry = project.character(name)
        characters.append({"name": name, "fixed_look": entry.tag_prompt() if entry else "(not in the bible)"})
    brief = {
        "page": spec.page, "panel": spec.panel, "attempt": attempt,
        "action": planned.action, "setting": planned.setting, "emotion": planned.emotion,
        "characters": characters, "expected_people": len(planned.characters),
        "shot": directed.shot, "angle": directed.angle, "composition": directed.composition,
        "speech_bubbles_needed": len(planned.dialogue) + (1 if planned.narration else 0),
        "image_prompt_used": prompt,
    }
    user = f"<panel_spec>\n{json.dumps(brief, indent=1)}\n</panel_spec>\n\nReview the panel image."
    images = review_images(job_dir, image, spec)
    return run_agent(
        agent="editor", label=f"Editor review p{spec.page}·{spec.panel} #{attempt}", llm=llm,
        system=system_prompt(), user=user, output_model=EditorReview, task="editor_review",
        # `context` is only read by the mock LLM (real models get the text + images above).
        context={**brief, "image_path": str(image), "consistency": consistency,
                 "seed": spec.seed if seed is None else seed},
        inputs_summary={"panel": f"p{spec.page}·{spec.panel}", "attempt": attempt, "images": len(images),
                        "shot": directed.shot, "characters": planned.characters},
        prices=prices, images=images,
    )


__all__ = ["review_panel", "system_prompt", "review_images", "AgentStep"]
