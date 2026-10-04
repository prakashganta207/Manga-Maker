"""Data models shared by every pipeline stage.

`MangaScript` is the contract between the LLM and the rest of the app.
The LLM is asked to return JSON matching this schema (we even send it the JSON
Schema generated from these classes), and Pydantic then *validates* what comes
back. LLMs occasionally produce wrong or incomplete JSON, so validation is the
safety net: invalid output is rejected and the model is asked to fix it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ShotType = Literal["close-up", "medium", "wide"]

# Speaker name used for lines that belong to no character (signs, sounds, etc.).
NARRATOR = "Narrator"


class CharacterSpec(BaseModel):
    """A main character's fixed look. Reused word-for-word in every image prompt."""

    name: str = Field(min_length=1, max_length=40)
    role: str = Field(default="", max_length=120, description="Who they are in the story")
    hair: str = Field(min_length=1, max_length=120)
    outfit: str = Field(min_length=1, max_length=160)
    features: str = Field(min_length=1, max_length=160, description="Face, build, age, accessories")


class DialogueLine(BaseModel):
    speaker: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=200)


class Panel(BaseModel):
    panel_number: int = Field(ge=1)
    characters: list[str] = Field(default_factory=list, description="Names of characters visible")
    action: str = Field(min_length=1, max_length=300, description="What is happening, visually")
    setting: str = Field(min_length=1, max_length=160)
    shot: ShotType = Field(description="Camera framing: close-up, medium or wide")
    mood: str = Field(min_length=1, max_length=60)
    dialogue: list[DialogueLine] = Field(default_factory=list, max_length=3)
    narration: str | None = Field(default=None, max_length=240)

    @field_validator("shot", mode="before")
    @classmethod
    def normalise_shot(cls, value: object) -> object:
        # Be forgiving about spelling ("Close up", "closeup", "WIDE") but strict on meaning.
        if isinstance(value, str):
            v = value.strip().lower().replace("_", "-").replace(" ", "-")
            aliases = {"closeup": "close-up", "close": "close-up", "medium-shot": "medium",
                       "wide-shot": "wide", "long": "wide", "establishing": "wide"}
            return aliases.get(v, v)
        return value

    @field_validator("narration", mode="before")
    @classmethod
    def empty_narration_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class Page(BaseModel):
    page_number: int = Field(ge=1)
    panels: list[Panel] = Field(min_length=1, max_length=6)


class MangaScript(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    characters: list[CharacterSpec] = Field(default_factory=list, max_length=8)
    pages: list[Page] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def check_references(self) -> "MangaScript":
        """Every name used in panels must be a declared character (or the narrator)."""
        known = {c.name.lower() for c in self.characters} | {NARRATOR.lower()}
        problems: list[str] = []
        for page in self.pages:
            for panel in page.panels:
                where = f"page {page.page_number} panel {panel.panel_number}"
                for name in panel.characters:
                    if name.lower() not in known:
                        problems.append(f"{where}: character '{name}' is not in the characters list")
                for line in panel.dialogue:
                    if line.speaker.lower() not in known:
                        problems.append(f"{where}: speaker '{line.speaker}' is not in the characters list")
        if problems:
            raise ValueError("; ".join(problems[:10]))
        return self

    def all_panels(self) -> list[tuple[Page, Panel]]:
        return [(page, panel) for page in self.pages for panel in page.panels]

    def renumber(self) -> "MangaScript":
        """Make page/panel numbers 1..n in order (LLMs sometimes skip or repeat)."""
        for p_index, page in enumerate(self.pages, start=1):
            page.page_number = p_index
            for n_index, panel in enumerate(page.panels, start=1):
                panel.panel_number = n_index
        return self
