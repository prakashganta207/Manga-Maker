"""Series memory: projects contain chapters that share a cast, LoRAs, art style and a running summary.

    OUTPUT_DIR/projects/<project_id>/series.json   title, style, story so far, chapter list
    OUTPUT_DIR/projects/<project_id>/cast.json     the approved cast (CastStore), LoRAs included

A new chapter (a job started with the project's id) gets:
  - the approved cast, with the same tags, seeds, reference sheets, look locks and LoRAs,
  - the series' art style tags,
  - the "story so far", which the Writer reads before planning the new chapter.
After the chapter is exported, the Writer updates the story so far (a summary of everything up to
now + open threads), so continuity carries into the next chapter.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..config import Settings
from .graph import Ctx
from .runner import AgentStep, run_agent
from .schemas import StorySoFar
from .state import MangaProject


class ChapterInfo(BaseModel):
    number: int
    job_id: str
    title: str = ""
    status: str = "running"
    summary: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    cover: str | None = None          # first page image (relative to the job folder)


class Series(BaseModel):
    project_id: str
    title: str = ""
    style_tags: str = ""
    story_so_far: str = ""
    open_threads: list[str] = Field(default_factory=list)
    character_notes: list[str] = Field(default_factory=list)
    chapters: list[ChapterInfo] = Field(default_factory=list)

    def chapter_for(self, job_id: str) -> ChapterInfo | None:
        return next((c for c in self.chapters if c.job_id == job_id), None)


class SeriesStore:
    def __init__(self, output_dir: Path):
        self.root = output_dir / "projects"

    def path(self, project_id: str) -> Path:
        return self.root / project_id / "series.json"

    def load(self, project_id: str) -> Series | None:
        path = self.path(project_id)
        return Series.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def save(self, series: Series) -> None:
        path = self.path(series.project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(series.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def list(self) -> list[Series]:
        if not self.root.exists():
            return []
        found = [Series.model_validate(json.loads(p.read_text(encoding="utf-8"))) for p in self.root.glob("*/series.json")]
        return sorted(found, key=lambda s: max((c.created_at for c in s.chapters), default=""), reverse=True)

    def register(self, project: MangaProject) -> Series:
        """Add (or update) this job as a chapter of its series."""
        series = self.load(project.project_id) or Series(project_id=project.project_id, style_tags=project.style_tags)
        chapter = series.chapter_for(project.job_id)
        if chapter is None:
            chapter = ChapterInfo(number=project.chapter, job_id=project.job_id)
            series.chapters.append(chapter)
            series.chapters.sort(key=lambda c: c.number)
        chapter.title = project.title or chapter.title
        chapter.status = project.status
        rtl = (project.outputs.get("rtl") or {}).get("pages") or []
        chapter.cover = rtl[0] if rtl else chapter.cover
        if not series.title:
            series.title = project.series_title or project.title
        self.save(series)
        return series


def setup_chapter(project: MangaProject, settings: Settings) -> None:
    """For a job that continues an existing series: chapter number, memory and style."""
    series = SeriesStore(settings.output_dir).load(project.project_id)
    if series is None or project.project_id == project.job_id:
        return
    done = [c for c in series.chapters if c.job_id != project.job_id]
    project.chapter = max((c.number for c in done), default=0) + 1
    project.series_title = series.title
    project.story_so_far = series.story_so_far
    project.style_tags = series.style_tags


SYSTEM = """You are the head writer of a manga series. Keep the series' running memory up to date.

You get the story so far (earlier chapters; may be empty for chapter 1) and the beat sheet of the chapter
that was just finished. Return:
- summary: the WHOLE story so far, including this chapter, in 3-8 sentences (who, where, what changed).
- chapter_summary: 1-3 sentences about this chapter only.
- open_threads: unresolved questions or promises the next chapter could pick up.
- character_notes: lasting changes to characters (relationships, injuries, new items, secrets learned).
Use only facts from the inputs. Answer with JSON only, matching the schema."""


def update_story_so_far(p: MangaProject, ctx: Ctx) -> AgentStep:
    assert p.beat_sheet
    beats = p.beat_sheet.model_dump(mode="json")
    user = (f"<series>{p.series_title or p.title}</series>\n<chapter>{p.chapter}</chapter>\n"
            f"<story_so_far>\n{p.story_so_far or '(this is the first chapter)'}\n</story_so_far>\n"
            f"<chapter_beat_sheet>\n{json.dumps(beats, indent=1)}\n</chapter_beat_sheet>")
    memory, step = run_agent(agent="writer_summary", label="Story so far", llm=ctx.llm, system=SYSTEM, user=user,
                             output_model=StorySoFar, task="story_so_far",
                             context={"story_so_far": p.story_so_far, "beat_sheet": beats, "chapter": p.chapter,
                                      "title": p.title},
                             inputs_summary={"chapter": p.chapter, "had_memory": bool(p.story_so_far)},
                             prices=ctx.prices)
    store = SeriesStore(ctx.settings.output_dir)
    series = store.register(p)
    series.story_so_far = memory.summary
    series.open_threads = memory.open_threads
    series.character_notes = memory.character_notes
    chapter = series.chapter_for(p.job_id)
    if chapter is not None:
        chapter.summary = memory.chapter_summary
    store.save(series)
    return step


def node_series(p: MangaProject, ctx: Ctx) -> None:
    """Writer: update the series memory. A failure here never fails a finished chapter."""
    from .runner import AgentFailed
    try:
        p.add_step(update_story_so_far(p, ctx))
    except AgentFailed as exc:
        p.add_step(exc.step)
        p.warn("The Writer could not update the story so far; the next chapter starts without it")
        SeriesStore(ctx.settings.output_dir).register(p)


def series_done(p: MangaProject) -> bool:
    return any(s.agent == "writer_summary" for s in p.trace)


def series_summary(series: Series, settings: Settings) -> dict[str, Any]:
    from .cast_store import CastStore
    cast = CastStore(settings.output_dir).load(series.project_id)
    return {**series.model_dump(mode="json"),
            "cast": [{"name": c.name, "role": c.role, "approved": c.approved, "look_locked": c.look_locked,
                      "lora": c.lora.status, "lora_trainer": c.lora.trainer, "tags": c.tag_prompt(),
                      "image": c.sheets.views.get("front")} for c in cast.values()]}
