"""Stage 1 — Story -> Script.

The LLM acts as a manga scriptwriter: it splits the story into pages and panels
and returns *structured output* — JSON matching the MangaScript schema — instead
of free text. We then validate it with Pydantic. If validation fails, we send the
error messages back to the model and ask it to fix its answer ("repair loop").
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from pydantic import ValidationError

from ..models import NARRATOR, MangaScript
from ..providers.base import LLMProvider, ProviderError

# Names of well-known copyrighted characters. The app only makes ORIGINAL
# characters; if one of these slips into the script it gets renamed.
BLOCKED_CHARACTER_NAMES = {
    "naruto", "sasuke", "goku", "vegeta", "luffy", "zoro", "pikachu", "ash ketchum", "mario", "luigi",
    "link", "zelda", "sonic", "mickey", "mickey mouse", "minnie", "donald duck", "spider-man", "spiderman",
    "batman", "superman", "wonder woman", "iron man", "hulk", "elsa", "harry potter", "hermione",
    "totoro", "sailor moon", "doraemon", "astro boy", "gojo", "tanjiro", "nezuko", "eren", "levi",
    "light yagami", "ichigo", "edward elric", "shinji", "asuka", "deku", "all might", "saitama",
    "kirby", "darth vader", "yoda", "frodo", "gandalf", "sherlock holmes",
}

SYSTEM_PROMPT = """You are a professional manga scriptwriter and storyboard artist.
You turn a short prose story into a manga script made of pages and panels.

Rules:
- Use ONLY the original characters from the user's story. Never introduce, name or
  reference existing copyrighted characters, franchises, or real artists' styles.
- Every name in a panel's "characters" list and every dialogue "speaker" must appear
  in the top-level "characters" list. Use "Narrator" as speaker only for off-panel voices.
- For each main character give a concrete, visual, unchanging description:
  hair (style + colour shade in black-and-white terms), outfit, and distinguishing
  features (face, build, age, accessories). These are reused in every image prompt
  to keep the character looking the same, so be specific and consistent.
- Each panel describes ONE moment that can be drawn: "action" is what we SEE.
- "shot" must be exactly one of: close-up, medium, wide. Vary shots like a real manga:
  open a scene with a wide establishing shot, use close-ups for emotion.
- Keep dialogue short (max 15 words per line, max 2 lines per panel). Put scene-setting
  text in "narration" (max 25 words), or null when not needed.
- Do not put any text in "action" that should be read by the reader; that belongs in
  dialogue or narration.
- Answer with JSON only, matching the provided schema exactly."""


def build_user_prompt(story: str, panels_per_page: int, max_pages: int, errors: list[str] | None = None) -> str:
    prompt = (
        f"Turn this story into a manga script with exactly {panels_per_page} panels per page "
        f"and at most {max_pages} page(s). Use fewer pages for short stories.\n\n"
        f"<story>\n{story.strip()}\n</story>"
    )
    if errors:
        # Repair loop: show the model exactly what was wrong with its last answer.
        prompt += (
            "\n\nYour previous answer was rejected by the validator with these errors:\n- "
            + "\n- ".join(errors[:15])
            + "\nReturn a corrected, complete JSON answer."
        )
    return prompt


class ScriptError(RuntimeError):
    """The LLM could not produce a valid script."""


def _parse(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        # Models sometimes wrap JSON in ```json fences — strip them.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    raise ValueError("Answer is not a JSON object")


def _error_list(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def sanitize_characters(script: MangaScript) -> list[str]:
    """Rename any well-known copyrighted character to a neutral original name."""
    warnings: list[str] = []
    renames: dict[str, str] = {}
    for index, character in enumerate(script.characters):
        if character.name.strip().lower() in BLOCKED_CHARACTER_NAMES:
            new_name = f"Original {chr(ord('A') + index)}"
            renames[character.name.lower()] = new_name
            warnings.append(f"Renamed '{character.name}' to '{new_name}' (only original characters are allowed)")
            character.name = new_name
    if renames:
        for _, panel in script.all_panels():
            panel.characters = [renames.get(n.lower(), n) for n in panel.characters]
            for line in panel.dialogue:
                line.speaker = renames.get(line.speaker.lower(), line.speaker)
    return warnings


def normalise(script: MangaScript, panels_per_page: int, max_pages: int) -> MangaScript:
    """Clamp page/panel counts, renumber, and make names match declared spelling."""
    script.pages = script.pages[:max_pages]
    for page in script.pages:
        page.panels = page.panels[: min(6, max(1, panels_per_page))]
    canonical = {c.name.lower(): c.name for c in script.characters}
    canonical[NARRATOR.lower()] = NARRATOR
    for _, panel in script.all_panels():
        panel.characters = [canonical.get(n.lower(), n) for n in panel.characters
                            if n.lower() != NARRATOR.lower()]
        for line in panel.dialogue:
            line.speaker = canonical.get(line.speaker.lower(), line.speaker)
    return script.renumber()


def generate_script(
    story: str,
    llm: LLMProvider,
    *,
    panels_per_page: int = 4,
    max_pages: int = 2,
    max_attempts: int = 3,
    on_attempt: Callable[[int], None] | None = None,
) -> tuple[MangaScript, list[str]]:
    """Run the LLM until it returns a valid script. Returns (script, warnings)."""
    story = story.strip()
    if not story:
        raise ScriptError("The story is empty")

    schema = MangaScript.model_json_schema()
    errors: list[str] | None = None
    for attempt in range(1, max_attempts + 1):
        if on_attempt:
            on_attempt(attempt)
        try:
            raw = llm.generate_json(
                system=SYSTEM_PROMPT,
                user=build_user_prompt(story, panels_per_page, max_pages, errors),
                schema=schema,
                task="manga_script",
                context={"story": story, "panels_per_page": panels_per_page, "max_pages": max_pages},
            )
            script = MangaScript.model_validate(_parse(getattr(raw, 'data', raw)))
        except (ValidationError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
            errors = _error_list(exc)
            continue
        except ProviderError as exc:
            raise ScriptError(f"LLM provider failed: {exc}") from exc

        warnings = sanitize_characters(script)
        return normalise(script, panels_per_page, max_pages), warnings

    raise ScriptError(f"LLM did not return a valid script after {max_attempts} attempts: {'; '.join(errors or [])}")
