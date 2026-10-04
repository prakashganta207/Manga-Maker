"""Writer agent — two passes.

Pass 1 (beat sheet): what happens, how it feels, where the climax is, who matters.
Pass 2 (page plan): turn beats into pages and panels with manga pacing:
  - a splash or large panel for the climax and big reveals
  - several small panels for fast action
  - quiet, medium panels for emotional beats
  - every page ends on a hook or a strong panel (readers turn the page for it)
"""

from __future__ import annotations

import json
import re

from . import safety
from .runner import AgentStep, run_agent
from .schemas import NARRATOR, BeatSheet, PagePlan
from .state import MangaProject

BEAT_SYSTEM = """You are the story editor of a manga studio. Break the user's story into a beat sheet.

Rules:
- A beat is one dramatic unit (something changes). Use 3-{max_beats} beats depending on story length, in story order, ids 1..n.
- For each beat: a short summary of what happens (keep the story's key dialogue), the dominant emotion,
  an intensity from 1 (quiet) to 5 (peak), and a kind: setup, rising, action, quiet, reveal, turn, climax, resolution.
- Exactly one beat is the climax (kind "climax", highest intensity); put its id in climax_beat.
- emotional_arc: one sentence describing how the feelings change from start to end.
- characters: ONLY characters that appear in the story, with the story's names. importance "main" for
  the 1-4 characters the story is about, "supporting" for the rest. Never introduce or reference
  existing copyrighted characters or franchises.
- Answer with JSON only, matching the schema."""

PAGE_SYSTEM = """You are a manga storyboard writer. Turn the beat sheet into pages and panels.

Manga pacing rules:
- Every beat is covered by at least one panel, in beat order. "beat" = the id of the beat a panel serves,
  "purpose" = why the panel exists (e.g. "establish the rooftop", "show her shock").
- size: "splash" (a whole page, use at most once, for the climax or the biggest reveal; a splash panel is
  alone on its page), "large" (climax/reveals/establishing; at most one per page), "medium" (default,
  dialogue and emotional beats), "small" (fast action: use several small panels in a row).
- 1 to {max_panels} panels per page, at most {max_pages} page(s). Prefer 3-5 panels per page.
- End every page on a cliffhanger, a reveal or a strong emotional panel; describe it in page_turn.
- characters: names from the beat sheet only. Dialogue speakers: those names or "Narrator".
- Keep dialogue short (max 15 words per line, max 2-3 lines per panel). Narration max 25 words, or null.
- sfx: short sound effects in capitals (e.g. "CRASH", "TAP TAP"), only when something makes a sound.
- action describes what we SEE in the picture; it must not contain text to be read.
- Answer with JSON only, matching the schema."""


def _names_in_story(names: list[str], story: str) -> list[str]:
    lower = story.lower()
    missing = []
    for name in names:
        tokens = [t for t in re.split(r"\W+", name.lower()) if len(t) > 1]
        if tokens and not any(t in lower for t in tokens):
            missing.append(name)
    return missing


def write_beat_sheet(project: MangaProject, llm, prices=(None, None)) -> AgentStep:
    story = project.story
    # Every beat needs at least one panel, so the page budget caps the number of beats.
    max_beats = max(3, project.max_pages * min(5, project.max_panels_per_page))

    def check(sheet: BeatSheet) -> list[str]:
        problems = [f"character '{n}' does not appear in the story; use only the story's characters"
                    for n in _names_in_story([c.name for c in sheet.characters], story)]
        if len(sheet.beats) > max_beats:
            problems.append(f"use at most {max_beats} beats (you used {len(sheet.beats)})")
        climax = sheet.beat(sheet.climax_beat)
        if climax and climax.intensity < max(b.intensity for b in sheet.beats):
            problems.append("the climax beat must have the highest intensity")
        return problems

    sheet, step = run_agent(
        agent="writer", label="Beat sheet", llm=llm, system=BEAT_SYSTEM.format(max_beats=max_beats),
        user=f"<story>\n{story}\n</story>", output_model=BeatSheet, task="beat_sheet",
        context={"story": story, "max_beats": max_beats},
        inputs_summary={"story_words": len(story.split()), "max_beats": max_beats},
        check=check, prices=prices,
    )
    # Only original characters: rename any well-known copyrighted one.
    renames = safety.rename_map([c.name for c in sheet.characters])
    for character in sheet.characters:
        new = safety.apply(character.name, renames)
        if new != character.name:
            step.notes.append(f"Renamed '{character.name}' to '{new}' (original characters only)")
            project.warn(step.notes[-1])
            character.name = new
    project.renames = renames
    project.beat_sheet = sheet
    project.title = sheet.title
    step.output = sheet.model_dump(mode="json")
    return step


def check_page_plan(plan: PagePlan, sheet: BeatSheet, max_pages: int, max_panels: int) -> list[str]:
    problems: list[str] = []
    if len(plan.pages) > max_pages:
        problems.append(f"use at most {max_pages} page(s); you used {len(plan.pages)}")
    known = {c.name.lower() for c in sheet.characters}
    beat_ids = {b.id for b in sheet.beats}
    seen: list[int] = []
    for page in plan.pages:
        if len(page.panels) > max_panels:
            problems.append(f"page {page.page_number} has {len(page.panels)} panels; max is {max_panels}")
        for panel in page.panels:
            where = f"page {page.page_number} panel {panel.panel_number}"
            if panel.beat not in beat_ids:
                problems.append(f"{where}: beat {panel.beat} does not exist")
            seen.append(panel.beat)
            for name in panel.characters:
                if name.lower() not in known:
                    problems.append(f"{where}: character '{name}' is not in the beat sheet")
            for line in panel.dialogue:
                if line.speaker.lower() not in known | {NARRATOR.lower()}:
                    problems.append(f"{where}: speaker '{line.speaker}' is not a character or Narrator")
    missing = sorted(beat_ids - set(seen))
    if missing:
        problems.append(f"beats {missing} are not covered by any panel")
    if seen != sorted(seen):
        problems.append("panels must follow beat order")
    return problems


def normalise_page_plan(plan: PagePlan, sheet: BeatSheet, renames: dict[str, str]) -> list[str]:
    """Small fixes done in code instead of another LLM round-trip. Returns notes."""
    notes: list[str] = []
    canonical = {c.name.lower(): c.name for c in sheet.characters} | {NARRATOR.lower(): NARRATOR}
    for page in plan.pages:
        if len(page.panels) > 1:
            for panel in page.panels:
                if panel.size == "splash":
                    panel.size = "large"
                    notes.append(f"page {page.page_number}: splash panel shares the page -> large")
        larges = [p for p in page.panels if p.size == "large"]
        if len(larges) > 1:
            # Keep the large panel for the most intense beat (the climax wins ties).
            def weight(p):
                beat = sheet.beat(p.beat)
                return ((beat.intensity if beat else 0), p.beat == sheet.climax_beat)

            keep = max(larges, key=weight)
            for extra in larges:
                if extra is not keep:
                    extra.size = "medium"
                    notes.append(f"page {page.page_number}: one large panel per page -> panel "
                                 f"{extra.panel_number} medium")
        if len(page.panels) == 1:
            page.panels[0].size = "splash"
        for panel in page.panels:
            panel.characters = [canonical.get(safety.apply(n, renames).lower(), n) for n in panel.characters]
            for line in panel.dialogue:
                line.speaker = canonical.get(safety.apply(line.speaker, renames).lower(), line.speaker)
    plan.renumber()
    return notes


def plan_pages(project: MangaProject, llm, prices=(None, None)) -> AgentStep:
    sheet = project.beat_sheet
    assert sheet is not None, "beat sheet missing"
    max_pages, max_panels = project.max_pages, project.max_panels_per_page
    system = PAGE_SYSTEM.format(max_pages=max_pages, max_panels=max_panels)
    user = (f"<story>\n{project.story}\n</story>\n\n<beat_sheet>\n"
            f"{json.dumps(sheet.model_dump(mode='json'), indent=1)}\n</beat_sheet>")
    plan, step = run_agent(
        agent="writer", label="Page plan", llm=llm, system=system, user=user, output_model=PagePlan,
        task="page_plan",
        context={"story": project.story, "beat_sheet": sheet.model_dump(mode="json"),
                 "max_pages": max_pages, "max_panels": max_panels},
        inputs_summary={"beats": len(sheet.beats), "max_pages": max_pages, "max_panels_per_page": max_panels},
        check=lambda p: check_page_plan(p, sheet, max_pages, max_panels), prices=prices,
    )
    step.notes.extend(normalise_page_plan(plan, sheet, project.renames))
    project.page_plan = plan
    step.output = plan.model_dump(mode="json")
    return step
