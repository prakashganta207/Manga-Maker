"""Character Designer agent — writes the character bible.

For each character: role, age range, body type, a canonical description, personality,
expression range, and a fixed set of visual tags (hair, eyes, outfit, accessories,
distinguishing marks). The tags are pasted word-for-word into every image prompt where
the character appears: image models have no memory, so repeating identical words is
the first line of defence for consistency (IP-Adapter references are the second).
"""

from __future__ import annotations

import hashlib
import json
import re

from .runner import AgentStep, run_agent
from .schemas import CharacterBibleDraft
from .state import CharacterEntry, MangaProject

SYSTEM = """You are the character designer of a black-and-white manga. Write a character bible entry for
each character listed.

Rules:
- Only the story's ORIGINAL characters, with exactly the names given. Never base a design on an existing
  copyrighted character, franchise, celebrity or real person.
- visual_tags are reused word-for-word in every image prompt, so make them concrete, visual, and
  distinctive between characters (silhouette, hairstyle and outfit should tell characters apart even
  in black and white). Describe colours as tones: "jet-black", "white", "light grey", "dark".
  hair: style + length + tone. eyes: shape/size. outfit: main clothing. accessories / distinguishing_marks:
  one item each or "none".
- description: 1-3 sentences, the canonical look.
- age_range, body_type, personality: short phrases. expression_range: the expressions this character
  shows in the story (e.g. neutral, happy, angry, sad, surprised).
- Answer with JSON only, matching the schema."""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "character"


def stable_seed(*parts: str) -> int:
    # Fixed seeds stored in the bible -> the same sheet can be redrawn identically.
    return int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:8], 16)


def design_characters(project: MangaProject, llm, prices=(None, None),
                      existing: dict[str, CharacterEntry] | None = None) -> AgentStep:
    """Design every beat-sheet character not already in `existing` (a reused cast)."""
    sheet = project.beat_sheet
    assert sheet is not None
    existing = existing or {}
    wanted = [c for c in sheet.characters if c.name.lower() not in existing]
    reused = [existing[c.name.lower()] for c in sheet.characters if c.name.lower() in existing]

    designs = []
    step: AgentStep
    if wanted:
        names = [c.name for c in wanted]

        def check(draft: CharacterBibleDraft) -> list[str]:
            got = [d.name.lower() for d in draft.characters]
            problems = [f"missing a bible entry for '{n}'" for n in names if n.lower() not in got]
            problems += [f"'{d.name}' is not one of the requested characters" for d in draft.characters
                         if d.name.lower() not in {n.lower() for n in names}]
            tags = [d.visual_tags.hair.lower() for d in draft.characters]
            if len(set(tags)) < len(tags):
                problems.append("give every character a different hair description so they are distinguishable")
            return problems

        listing = [c.model_dump(mode="json") for c in wanted]
        user = (f"<story>\n{project.story}\n</story>\n\n<characters>\n{json.dumps(listing, indent=1)}\n</characters>")
        draft, step = run_agent(
            agent="character_designer", label="Character bible", llm=llm, system=SYSTEM, user=user,
            output_model=CharacterBibleDraft, task="character_bible",
            context={"beat_sheet": {**sheet.model_dump(mode="json"), "characters": listing}},
            inputs_summary={"characters": names, "reused": [c.name for c in reused]},
            check=check, prices=prices,
        )
        designs = list(draft.characters)  # names were already made original by the Writer
    else:
        step = AgentStep(agent="character_designer", label="Character bible", status="skipped",
                     notes=["All characters reused from the project's cast"],
                     inputs={"reused": [c.name for c in reused]})

    entries: list[CharacterEntry] = []
    for character in sheet.characters:
        key = character.name.lower()
        if key in existing:
            entry = existing[key].model_copy(deep=True)
            entries.append(entry)
            step.notes.append(f"Reused {entry.name} from project cast (approved={entry.approved})")
            continue
        design = next(d for d in designs if d.name.lower() == key).model_dump()
        design["name"] = character.name
        entries.append(CharacterEntry(
            **design, slug=slugify(character.name),
            turnaround_seed=stable_seed(project.project_id, character.name, "turnaround"),
            expression_seed=stable_seed(project.project_id, character.name, "expressions"),
        ))
    project.characters = entries
    step.output = [e.model_dump(mode="json", include={"name", "role", "age_range", "body_type", "description",
                                                       "visual_tags", "personality", "expression_range"})
                   for e in entries]
    return step
