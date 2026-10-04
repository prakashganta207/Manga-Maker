"""Director agent — layout per page, camera per panel.

The LLM picks a layout template for each page and a shot type, camera angle and short
composition note for each panel. Then plain code enforces the house rules (LLMs follow
rules most of the time, code follows them every time):

  1. Establishing shot whenever the setting changes.
  2. A close-up (or extreme close-up) on every emotional peak.
  3. Never more than 2 identical shot types in a row.
"""

from __future__ import annotations

import json
import re

from ..pipeline import templates as layouts
from .runner import AgentStep, run_agent
from .schemas import CLOSE_SHOTS, SHOT_TYPES, BeatSheet, DirectorPlan, PagePlan, PlannedPanel
from .state import MangaProject

PEAK_EMOTIONS = {"shock", "shocked", "fear", "afraid", "terror", "grief", "sad", "sadness", "despair",
                 "anger", "angry", "rage", "love", "joy", "relief", "awe", "surprise", "surprised",
                 "heartbreak", "tears", "melancholy", "determination", "determined", "betrayal"}

# Alternatives tried (in order) when a shot must change to break a run of 3.
ALTERNATIVES = {
    "medium": ["close-up", "wide", "over-the-shoulder"],
    "close-up": ["medium", "extreme close-up", "over-the-shoulder"],
    "extreme close-up": ["close-up", "medium"],
    "wide": ["medium", "close-up"],
    "establishing": ["wide", "medium"],
    "over-the-shoulder": ["close-up", "medium"],
}

SYSTEM = """You are the director of a manga. For each page choose a layout template, and for each panel a shot
type, camera angle and a short composition note.

Layout templates (slots in reading order, size classes must suit the panels' planned sizes; the template's
panel count MUST equal the page's panel count):
{templates}

Shot types: extreme close-up, close-up, medium, wide, establishing, over-the-shoulder.
Camera angles: eye level, low (heroic, threatening), high (small, vulnerable), bird's eye (overview, isolation).

Rules:
- Use an establishing shot whenever the setting changes (including the very first panel).
- Use a close-up or extreme close-up on emotional peaks (the climax, shock, grief, confessions...).
- Never use the same shot type more than twice in a row. Vary angles for rhythm.
- composition: one short sentence: where characters are in the frame, what is in focus, foreground/background.
- Reading order is right-to-left (manga); "first" means the top-right panel.
- Answer with JSON only, matching the schema."""


def setting_key(setting: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", setting.lower()).split()
    return " ".join(w for w in words if w not in ("a", "an", "the", "of", "in", "on", "at"))


def is_peak(panel: PlannedPanel, sheet: BeatSheet) -> bool:
    beat = sheet.beat(panel.beat)
    if beat is None:
        return False
    if beat.id == sheet.climax_beat or beat.intensity == 5:
        return True
    emotion = panel.emotion.lower()
    return beat.intensity >= 4 and beat.kind != "action" and any(e in emotion for e in PEAK_EMOTIONS)


def check_director(plan: DirectorPlan, page_plan: PagePlan) -> list[str]:
    problems = []
    if len(plan.pages) != len(page_plan.pages):
        problems.append(f"direct all {len(page_plan.pages)} pages (got {len(plan.pages)})")
    for directed, planned in zip(plan.pages, page_plan.pages):
        if directed.layout not in layouts.BY_ID:
            problems.append(f"page {planned.page_number}: unknown layout '{directed.layout}'")
        elif layouts.get(directed.layout).panel_count != len(planned.panels):
            problems.append(f"page {planned.page_number}: layout '{directed.layout}' has "
                            f"{layouts.get(directed.layout).panel_count} slots but the page has {len(planned.panels)} panels")
        if len(directed.panels) != len(planned.panels):
            problems.append(f"page {planned.page_number}: direct every panel ({len(planned.panels)} panels)")
    return problems


def enforce_rules(plan: DirectorPlan, page_plan: PagePlan, sheet: BeatSheet) -> list[str]:
    """Fix rule violations in place. Returns human-readable notes for the timeline."""
    fixes: list[str] = []
    planned = [panel for _, panel in page_plan.all_panels()]
    directed = [panel for page in plan.pages for panel in page.panels]
    pages = [page.page_number for page in page_plan.pages for _ in page.panels]
    label = lambda i: f"p{pages[i]}·{planned[i].panel_number}"  # noqa: E731
    lock: dict[int, str] = {}  # index -> "establishing" | "close"

    # Rule 1: establishing shot on setting change.
    previous = None
    for i, panel in enumerate(planned):
        key = setting_key(panel.setting)
        if key != previous:
            lock[i] = "establishing"
            if directed[i].shot != "establishing":
                fixes.append(f"{label(i)}: setting changes to '{panel.setting}' → establishing "
                             f"(was {directed[i].shot})")
                directed[i].shot = "establishing"
        previous = key

    # Rule 2: every emotional peak beat gets at least one close shot.
    peak_beats: dict[int, list[int]] = {}
    for i, panel in enumerate(planned):
        if is_peak(panel, sheet):
            peak_beats.setdefault(panel.beat, []).append(i)
    for beat_id, indexes in peak_beats.items():
        if any(directed[i].shot in CLOSE_SHOTS for i in indexes):
            for i in indexes:
                if directed[i].shot in CLOSE_SHOTS:
                    lock.setdefault(i, "close")
            continue
        free = [i for i in indexes if lock.get(i) != "establishing"]
        if not free:
            fixes.append(f"beat {beat_id}: emotional peak in a new setting — kept the establishing shot")
            continue
        i = free[-1]
        fixes.append(f"{label(i)}: emotional peak (beat {beat_id}) → close-up (was {directed[i].shot})")
        directed[i].shot = "close-up"
        lock[i] = "close"

    # Rule 3: no more than 2 identical shots in a row.
    for _ in range(len(directed) * 2):
        run_end = next((i for i in range(2, len(directed))
                        if directed[i].shot == directed[i - 1].shot == directed[i - 2].shot), None)
        if run_end is None:
            break
        shot = directed[run_end].shot
        changed = False
        for i in (run_end - 1, run_end, run_end - 2):  # prefer changing the middle one
            if lock.get(i) == "establishing":
                continue
            options = ALTERNATIVES[shot]
            if lock.get(i) == "close":
                options = [s for s in options if s in CLOSE_SHOTS]  # stay a close shot
            neighbours = {directed[j].shot for j in (i - 1, i + 1) if 0 <= j < len(directed)}
            choice = next((s for s in options if s not in neighbours and s != shot), None)
            if choice:
                fixes.append(f"{label(i)}: third '{shot}' in a row → {choice}")
                directed[i].shot = choice
                changed = True
                break
        if not changed:
            fixes.append(f"{label(run_end)}: could not break a run of '{shot}' without breaking another rule")
            break
    return fixes


def direct(project: MangaProject, llm, prices=(None, None)) -> AgentStep:
    sheet, page_plan = project.beat_sheet, project.page_plan
    assert sheet is not None and page_plan is not None
    catalogue = "\n".join(
        f"- {t.id} ({t.panel_count} panels): {t.description} Slots: {', '.join(t.sizes)}" for t in layouts.TEMPLATES)
    user = (f"<beat_sheet>\n{json.dumps(sheet.model_dump(mode='json'), indent=1)}\n</beat_sheet>\n\n"
            f"<page_plan>\n{json.dumps(page_plan.model_dump(mode='json'), indent=1)}\n</page_plan>")
    plan, step = run_agent(
        agent="director", label="Director plan", llm=llm, system=SYSTEM.format(templates=catalogue), user=user,
        output_model=DirectorPlan, task="director",
        context={"page_plan": page_plan.model_dump(mode="json"), "beat_sheet": sheet.model_dump(mode="json")},
        inputs_summary={"pages": len(page_plan.pages), "panels": len(page_plan.all_panels()),
                        "templates": len(layouts.TEMPLATES)},
        check=lambda p: check_director(p, page_plan), prices=prices,
    )
    for i, page in enumerate(plan.pages, start=1):  # align numbering with the page plan
        page.page_number = i
        for j, panel in enumerate(page.panels, start=1):
            panel.panel_number = j
    fixes = enforce_rules(plan, page_plan, sheet)
    step.notes.extend(fixes)
    project.rule_fixes = fixes
    project.director = plan
    step.output = plan.model_dump(mode="json")
    return step


def shot_runs_ok(plan: DirectorPlan) -> bool:
    shots = [p.shot for page in plan.pages for p in page.panels]
    return not any(shots[i] == shots[i - 1] == shots[i - 2] for i in range(2, len(shots)))


__all__ = ["direct", "enforce_rules", "check_director", "is_peak", "setting_key", "shot_runs_ok", "SHOT_TYPES"]
