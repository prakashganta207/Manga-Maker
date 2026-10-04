"""Writer agent (beat sheet + page plan), project state persistence, LangGraph resume."""

import json

import pytest

from app.agents.graph import Ctx, Node, run_graph
from app.agents.schemas import PagePlan
from app.agents.state import MangaProject
from app.agents.writer import check_page_plan, normalise_page_plan, plan_pages, write_beat_sheet
from app.providers.base import LLMResponse
from app.providers.mock_image import MockImageProvider
from app.providers.mock_llm import MockLLMProvider

ACTION = (
    "Kenji sprinted across the rooftops as the alarm screamed. Drones swept the alley below! "
    "He leapt the gap and crashed onto the tiles. \"Give it back!\" Aya shouted from behind. "
    "She was faster than him. Kenji turned and hurled the stolen box into the river. "
    "The box exploded in a column of light! Aya stopped, stunned. \"What did you do?\" she whispered. "
    "Kenji smiled sadly. \"I set it free,\" he said."
)


class CountingLLM(MockLLMProvider):
    def __init__(self):
        self.calls = []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs["task"])
        return super().generate_json(**kwargs)


def new_project(story, **kw):
    return MangaProject(job_id="job1", project_id="proj1", story=story, **kw)


def writer_nodes():
    return [
        Node("writer_beats", "writer", "Beat sheet", lambda p, c: p.add_step(write_beat_sheet(p, c.llm)),
             lambda p: p.beat_sheet is not None),
        Node("writer_pages", "writer", "Page plan", lambda p, c: p.add_step(plan_pages(p, c.llm)),
             lambda p: p.page_plan is not None),
    ]


def test_mock_beat_sheet(story):
    project = new_project(story)
    step = write_beat_sheet(project, MockLLMProvider())
    sheet = project.beat_sheet
    assert step.status == "ok" and step.agent == "writer"
    assert {c.name for c in sheet.characters} >= {"Mira", "Kaito"}
    climax = sheet.beat(sheet.climax_beat)
    assert climax.kind == "climax" and climax.intensity == 5
    assert project.title == sheet.title


@pytest.mark.parametrize("max_pages", [1, 2])
def test_mock_page_plan_follows_pacing_rules(max_pages):
    project = new_project(ACTION, max_pages=max_pages)
    write_beat_sheet(project, MockLLMProvider())
    plan_pages(project, MockLLMProvider())
    plan, sheet = project.page_plan, project.beat_sheet
    assert check_page_plan(plan, sheet, max_pages, 6) == []
    assert len(plan.pages) <= max_pages
    climax_panels = [p for _, p in plan.all_panels() if p.beat == sheet.climax_beat]
    assert any(p.size in ("splash", "large") for p in climax_panels)
    for page in plan.pages:
        assert sum(p.size == "large" for p in page.panels) <= 1
    all_sfx = [s for _, p in plan.all_panels() for s in p.sfx]
    assert all_sfx, "action story should have sound effects"


def test_action_beats_get_small_panels():
    project = new_project(ACTION, max_pages=2)
    write_beat_sheet(project, MockLLMProvider())
    plan_pages(project, MockLLMProvider())
    sizes = [p.size for _, p in project.page_plan.all_panels()]
    assert "small" in sizes


def test_check_page_plan_finds_problems(story):
    project = new_project(story)
    write_beat_sheet(project, MockLLMProvider())
    plan_pages(project, MockLLMProvider())
    data = project.page_plan.model_dump()
    data["pages"][0]["panels"][0]["characters"] = ["Stranger"]
    data["pages"][0]["panels"] = data["pages"][0]["panels"][1:]  # drop beat 1
    problems = check_page_plan(PagePlan.model_validate(data), project.beat_sheet, 1, 6)
    assert any("not covered" in p for p in problems) or any("Stranger" in p for p in problems)


def test_normalise_fixes_sizes(story):
    project = new_project(story)
    write_beat_sheet(project, MockLLMProvider())
    plan_pages(project, MockLLMProvider())
    page = project.page_plan.pages[0]
    for panel in page.panels:
        panel.size = "splash"
    notes = normalise_page_plan(project.page_plan, project.beat_sheet, {})
    sizes = [p.size for p in page.panels]
    assert "splash" not in sizes and sizes.count("large") <= 1 and notes


def test_copyrighted_character_renamed():
    class RenamingLLM(MockLLMProvider):
        def generate_json(self, **kwargs):
            response = super().generate_json(**kwargs)
            text = json.dumps(response.data).replace("Mira", "Naruto")
            return LLMResponse(json.loads(text), model="mock")

    project = new_project("Naruto ran to the gate. Naruto smiled at the sky. \"Finally!\" Naruto said.")
    step = write_beat_sheet(project, RenamingLLM())
    names = [c.name for c in project.beat_sheet.characters]
    assert "Naruto" not in names and step.notes and project.warnings


def test_project_save_and_load(tmp_path, story):
    project = new_project(story)
    write_beat_sheet(project, MockLLMProvider())
    project.save(tmp_path)
    loaded = MangaProject.load(tmp_path)
    assert loaded.beat_sheet == project.beat_sheet and loaded.job_id == "job1"


def test_graph_runs_and_resumes(tmp_path, story, settings):
    llm = CountingLLM()
    ctx = Ctx(settings=settings, llm=llm, image=MockImageProvider(), job_dir=tmp_path)
    project = run_graph(new_project(story), writer_nodes(), ctx)
    assert project.page_plan is not None and llm.calls == ["beat_sheet", "page_plan"]
    assert [s.label for s in project.trace] == ["Beat sheet", "Page plan"]
    assert set(project.timings) == {"writer_beats", "writer_pages"}

    # Resume from disk: nothing is recomputed.
    llm.calls.clear()
    events = []
    ctx.progress = lambda stage, f, m: events.append(m)
    resumed = run_graph(MangaProject.load(tmp_path), writer_nodes(), ctx)
    assert llm.calls == [] and all("resumed" in m for m in events)
    assert resumed.page_plan == project.page_plan


def test_graph_gate_stops_run(tmp_path, story, settings):
    ctx = Ctx(settings=settings, llm=MockLLMProvider(), image=MockImageProvider(), job_dir=tmp_path)
    project = run_graph(new_project(story), writer_nodes(), ctx, gate_after="writer_beats", gate=lambda p: False)
    assert project.beat_sheet is not None and project.page_plan is None
