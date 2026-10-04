"""The shared agent state: one `MangaProject` per job, saved to disk after every step.

Think of it as the studio's job folder. Every agent reads what earlier agents wrote
(beat sheet → page plan → director plan → character bible → prompts → panels) and adds
its own part. Because it's saved as `project.json` after each step, a job can stop
(e.g. waiting for cast approval, or after a crash) and resume where it left off.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .runner import AgentStep
from .schemas import BeatSheet, CharacterDesign, DirectorPlan, PagePlan

PROJECT_FILE = "project.json"

EXPRESSIONS = ["neutral", "happy", "angry", "sad", "surprised"]
VIEWS = ["front", "side", "back"]


class CharacterSheets(BaseModel):
    """Reference images for one character (paths relative to the job folder)."""

    turnaround: str | None = None              # full sheet: front, side, back
    expressions: str | None = None             # full sheet: 5 expressions
    views: dict[str, str] = Field(default_factory=dict)        # "front" -> cropped image
    expression_refs: dict[str, str] = Field(default_factory=dict)  # "happy" -> cropped image


class CharacterEntry(CharacterDesign):
    """A character bible entry: the design + generated sheets + approval state."""

    slug: str = ""
    # Fixed seeds -> the same sheet can be regenerated identically (or changed on purpose).
    turnaround_seed: int = 0
    expression_seed: int = 0
    sheets: CharacterSheets = Field(default_factory=CharacterSheets)
    status: str = "designed"        # designed | generating | ready | approved
    approved: bool = False
    version: int = 1
    reused_from: str | None = None  # project id, when the character came from an earlier chapter

    def tag_prompt(self) -> str:
        return self.visual_tags.as_prompt()


class PanelPrompt(BaseModel):
    page: int
    panel: int
    prompt: str
    negative_prompt: str
    seed: int
    width: int
    height: int
    characters: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)  # reference image paths used (IP-Adapter)
    reference_kinds: list[str] = Field(default_factory=list)  # e.g. "Mira: happy"
    ipadapter_weight: float | None = None


class PanelResult(BaseModel):
    page: int
    panel: int
    image: str                       # path relative to the job folder
    seconds: float = 0.0
    workflow: str = ""
    # CLIP similarity between this panel and each character's references (0..1-ish).
    consistency: dict[str, float] = Field(default_factory=dict)
    consistency_method: str = ""


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class MangaProject(BaseModel):
    job_id: str
    project_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    story: str
    title: str = ""
    status: str = "running"          # running | awaiting_approval | done | failed
    auto_approve: bool = False
    max_pages: int = 2
    max_panels_per_page: int = 6
    providers: dict[str, Any] = Field(default_factory=dict)

    beat_sheet: BeatSheet | None = None
    page_plan: PagePlan | None = None
    director: DirectorPlan | None = None
    rule_fixes: list[str] = Field(default_factory=list)
    characters: list[CharacterEntry] = Field(default_factory=list)
    renames: dict[str, str] = Field(default_factory=dict)
    prompts: list[PanelPrompt] = Field(default_factory=list)
    panels: list[PanelResult] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)

    trace: list[AgentStep] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    timings: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    # ------------------------------------------------------------------ helpers
    def add_step(self, step: AgentStep) -> None:
        self.trace.append(step)
        self.usage.input_tokens += step.input_tokens
        self.usage.output_tokens += step.output_tokens
        self.usage.cost_usd = round(self.usage.cost_usd + step.cost_usd, 6)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def character(self, name: str) -> CharacterEntry | None:
        key = name.strip().lower()
        return next((c for c in self.characters if c.name.lower() == key), None)

    def main_character_names(self) -> list[str]:
        if not self.beat_sheet:
            return [c.name for c in self.characters]
        return [c.name for c in self.beat_sheet.main_characters()]

    def all_approved(self) -> bool:
        main = {n.lower() for n in self.main_character_names()}
        return all(c.approved for c in self.characters if c.name.lower() in main)

    def panel_result(self, page: int, panel: int) -> PanelResult | None:
        return next((p for p in self.panels if p.page == page and p.panel == panel), None)

    # ------------------------------------------------------------------ persistence
    def save(self, job_dir: Path) -> Path:
        job_dir.mkdir(parents=True, exist_ok=True)
        path = job_dir / PROJECT_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written file
        return path

    @classmethod
    def load(cls, job_dir: Path) -> "MangaProject":
        return cls.model_validate(json.loads((job_dir / PROJECT_FILE).read_text(encoding="utf-8")))

    @classmethod
    def exists(cls, job_dir: Path) -> bool:
        return (job_dir / PROJECT_FILE).exists()
