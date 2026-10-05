"""Structured outputs of every agent.

Each agent must answer with JSON matching one of these Pydantic models. We send the
model's JSON Schema to the LLM ("structured output") and validate the reply with
Pydantic; if it fails, the error text goes back to the LLM for a retry.
Validators here check one answer on its own; cross-checks against earlier agents'
outputs (e.g. "is this character in the beat sheet?") live in the agents.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

NARRATOR = "Narrator"

ShotType = Literal["extreme close-up", "close-up", "medium", "wide", "establishing", "over-the-shoulder"]
CameraAngle = Literal["eye level", "low", "high", "bird's eye"]
PanelSize = Literal["splash", "large", "medium", "small"]
BeatKind = Literal["setup", "rising", "action", "quiet", "reveal", "turn", "climax", "resolution"]

SHOT_TYPES: tuple[str, ...] = ShotType.__args__  # type: ignore[attr-defined]
CAMERA_ANGLES: tuple[str, ...] = CameraAngle.__args__  # type: ignore[attr-defined]
CLOSE_SHOTS = ("extreme close-up", "close-up")


def _norm(value: object, aliases: dict[str, str]) -> object:
    """Forgive spelling variants like "Close Up" / "closeup" / "birds-eye"."""
    if isinstance(value, str):
        v = value.strip().lower().replace("_", " ").replace("-", " ")
        v = " ".join(v.split())
        return aliases.get(v, value.strip().lower())
    return value


_SHOT_ALIASES = {
    "extreme close up": "extreme close-up", "extreme closeup": "extreme close-up", "ecu": "extreme close-up",
    "close up": "close-up", "closeup": "close-up", "cu": "close-up", "medium shot": "medium", "mid": "medium",
    "wide shot": "wide", "long shot": "wide", "establishing shot": "establishing",
    "over the shoulder": "over-the-shoulder", "ots": "over-the-shoulder",
}
_ANGLE_ALIASES = {
    "eye level": "eye level", "eye": "eye level", "eyelevel": "eye level", "low angle": "low",
    "high angle": "high", "birds eye": "bird's eye", "bird's eye": "bird's eye", "bird eye": "bird's eye",
    "birdseye": "bird's eye", "bird's eye view": "bird's eye", "top down": "bird's eye",
}


class DialogueLine(BaseModel):
    speaker: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=200)


# ----------------------------------------------------------------------------- Writer pass 1
class StoryCharacter(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(min_length=1, max_length=120, description="e.g. protagonist, rival, mentor")
    importance: Literal["main", "supporting"] = "main"
    summary: str = Field(default="", max_length=300)


class Beat(BaseModel):
    id: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=400, description="What happens in this beat")
    emotion: str = Field(min_length=1, max_length=40, description="Dominant emotion, one or two words")
    intensity: int = Field(ge=1, le=5, description="1 = quiet, 5 = peak")
    kind: BeatKind


class BeatSheet(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    logline: str = Field(min_length=1, max_length=300)
    emotional_arc: str = Field(min_length=1, max_length=300, description="How feelings change across the story")
    beats: list[Beat] = Field(min_length=2, max_length=24)
    climax_beat: int = Field(ge=1, description="id of the climax beat")
    characters: list[StoryCharacter] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def check(self) -> "BeatSheet":
        ids = [b.id for b in self.beats]
        if len(set(ids)) != len(ids):
            raise ValueError("beat ids must be unique")
        if self.climax_beat not in ids:
            raise ValueError(f"climax_beat {self.climax_beat} is not one of the beat ids {ids}")
        names = [c.name.lower() for c in self.characters]
        if len(set(names)) != len(names):
            raise ValueError("character names must be unique")
        return self

    def beat(self, beat_id: int) -> Beat | None:
        return next((b for b in self.beats if b.id == beat_id), None)

    def main_characters(self) -> list[StoryCharacter]:
        return [c for c in self.characters if c.importance == "main"] or self.characters[:1]


# ----------------------------------------------------------------------------- Writer pass 2
class PlannedPanel(BaseModel):
    panel_number: int = Field(ge=1)
    beat: int = Field(ge=1, description="id of the beat this panel serves")
    purpose: str = Field(min_length=1, max_length=200, description="Why this panel exists")
    size: PanelSize = Field(description="splash/large for climax and reveals, small for fast action")
    characters: list[str] = Field(default_factory=list, max_length=4)
    action: str = Field(min_length=1, max_length=300, description="What we SEE")
    setting: str = Field(min_length=1, max_length=160)
    emotion: str = Field(min_length=1, max_length=40)
    dialogue: list[DialogueLine] = Field(default_factory=list, max_length=3)
    narration: str | None = Field(default=None, max_length=240)
    sfx: list[str] = Field(default_factory=list, max_length=3, description="Sound effects, e.g. CRASH")

    @field_validator("narration", mode="before")
    @classmethod
    def empty_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("sfx")
    @classmethod
    def short_sfx(cls, v: list[str]) -> list[str]:
        return [s.strip().upper()[:20] for s in v if s.strip()]


class PlannedPage(BaseModel):
    page_number: int = Field(ge=1)
    panels: list[PlannedPanel] = Field(min_length=1, max_length=6)
    page_turn: str = Field(default="", max_length=200, description="The hook or strong beat that ends the page")


class PagePlan(BaseModel):
    pages: list[PlannedPage] = Field(min_length=1, max_length=10)

    def all_panels(self) -> list[tuple[PlannedPage, PlannedPanel]]:
        return [(p, panel) for p in self.pages for panel in p.panels]

    def renumber(self) -> "PagePlan":
        for i, page in enumerate(self.pages, start=1):
            page.page_number = i
            for j, panel in enumerate(page.panels, start=1):
                panel.panel_number = j
        return self


# ----------------------------------------------------------------------------- Director
class DirectedPanel(BaseModel):
    panel_number: int = Field(ge=1)
    shot: ShotType
    angle: CameraAngle
    composition: str = Field(min_length=1, max_length=200, description="Short note: framing, placement, focus")

    @field_validator("shot", mode="before")
    @classmethod
    def norm_shot(cls, v: object) -> object:
        return _norm(v, _SHOT_ALIASES)

    @field_validator("angle", mode="before")
    @classmethod
    def norm_angle(cls, v: object) -> object:
        return _norm(v, _ANGLE_ALIASES)


class DirectedPage(BaseModel):
    page_number: int = Field(ge=1)
    layout: str = Field(min_length=1, max_length=40, description="id of a layout template")
    panels: list[DirectedPanel] = Field(min_length=1, max_length=6)


class DirectorPlan(BaseModel):
    pages: list[DirectedPage] = Field(min_length=1, max_length=10)


# ----------------------------------------------------------------------------- Character Designer
class VisualTags(BaseModel):
    """Fixed visual tags. Pasted EXACTLY into every prompt for this character —
    repeating identical words is the simplest way to keep a character consistent."""

    hair: str = Field(min_length=1, max_length=80, description="e.g. 'short spiky black hair'")
    eyes: str = Field(min_length=1, max_length=60, description="e.g. 'narrow dark eyes'")
    outfit: str = Field(min_length=1, max_length=120)
    accessories: str = Field(default="none", max_length=80)
    distinguishing_marks: str = Field(default="none", max_length=80)

    def as_prompt(self) -> str:
        parts = [self.hair, self.eyes, self.outfit]
        for extra in (self.accessories, self.distinguishing_marks):
            if extra and extra.strip().lower() not in ("none", "n/a", "-"):
                parts.append(extra)
        return ", ".join(p.strip() for p in parts if p.strip())


class CharacterDesign(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(min_length=1, max_length=120)
    age_range: str = Field(min_length=1, max_length=30, description="e.g. 'mid teens', 'late 30s'")
    body_type: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=400, description="Canonical visual description")
    visual_tags: VisualTags
    personality: str = Field(min_length=1, max_length=200)
    expression_range: list[str] = Field(default_factory=list, max_length=8)


class CharacterBibleDraft(BaseModel):
    characters: list[CharacterDesign] = Field(min_length=1, max_length=8)


# ----------------------------------------------------------------------------- Editor (Phase 3)
# The Editor is a *vision* LLM: it looks at a finished panel next to the Director's spec and the
# character references, and grades it like a manga editor would. Each criterion is scored 1-5:
#   5 = perfect, 4 = good, 3 = acceptable with flaws, 2 = clearly wrong, 1 = completely wrong.
EDITOR_CRITERIA: dict[str, str] = {
    "script_action": "the picture shows the action described in the panel spec",
    "characters": "the right characters are in the panel (nobody missing, nobody extra)",
    "people_count": "the number of people matches the spec (0 for scenery panels)",
    "character_likeness": "each character's hair, face, outfit and accessories match their reference images",
    "shot_angle": "the shot type (close-up, wide...) and camera angle (low, high...) match the spec",
    "emotion": "faces and body language show the panel's emotion",
    "anatomy": "hands, faces and limbs are well formed (no extra fingers, melted faces, broken limbs)",
    "manga_style": "black-and-white manga look: ink lines, screentone, no colour, no photo/3D look, no text",
    "bubble_space": "the composition leaves calm areas (sky, wall, background) where speech bubbles can go",
}


class EditorScores(BaseModel):
    script_action: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["script_action"])
    characters: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["characters"])
    people_count: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["people_count"])
    character_likeness: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["character_likeness"])
    shot_angle: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["shot_angle"])
    emotion: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["emotion"])
    anatomy: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["anatomy"])
    manga_style: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["manga_style"])
    bubble_space: int = Field(ge=1, le=5, description=EDITOR_CRITERIA["bubble_space"])

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in EDITOR_CRITERIA}


class EditorFix(BaseModel):
    """A concrete, machine-applicable fix for the next attempt."""

    prompt_add: list[str] = Field(default_factory=list, max_length=8,
                                  description="Short image-prompt tags to ADD, e.g. 'from below', 'clenched fists'")
    prompt_remove: list[str] = Field(default_factory=list, max_length=8,
                                     description="Tags currently in the prompt that caused the problem")
    negative_add: list[str] = Field(default_factory=list, max_length=8,
                                    description="Tags to add to the negative prompt, e.g. 'extra fingers', 'color'")
    ipadapter_weight: float | None = Field(default=None, ge=0.0, le=1.2,
                                           description="New character-reference strength (0.3-1.0), or null to keep")
    new_seed: bool = Field(default=False, description="True to start from different random noise")

    @field_validator("prompt_add", "prompt_remove", "negative_add")
    @classmethod
    def clean_tags(cls, v: list[str]) -> list[str]:
        tags = [" ".join(t.replace(",", " ").split())[:60] for t in v]
        return [t for t in tags if t]

    def is_empty(self) -> bool:
        return not (self.prompt_add or self.prompt_remove or self.negative_add or self.new_seed
                    or self.ipadapter_weight is not None)


class EditorReview(BaseModel):
    scores: EditorScores
    verdict: Literal["pass", "fail"]
    problems: list[str] = Field(default_factory=list, max_length=8,
                                description="Specific problems you can see, e.g. 'Aya has short hair; reference shows twin tails'")
    fix: EditorFix = Field(default_factory=EditorFix)
    reasoning: str = Field(min_length=1, max_length=800, description="Two to four sentences explaining the scores")

    @field_validator("verdict", mode="before")
    @classmethod
    def norm_verdict(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def check(self) -> "EditorReview":
        if self.verdict == "fail":
            if not self.problems:
                raise ValueError("a failing review must list the problems")
            if self.fix.is_empty():
                raise ValueError("a failing review must give a concrete fix (prompt/negative changes, "
                                 "ipadapter_weight or new_seed)")
        return self
