"""Phase 4 M5: panel instructions -> Panel Revision agent -> redraw through the Editor loop."""

import time

import pytest
from fastapi.testclient import TestClient

from app.agents.pipeline import new_project, run_project
from app.agents.revision import apply_revision, find_panel, revise_spec
from app.agents.schemas import PanelRevision
from app.main import create_app
from app.providers.base import LLMResponse
from app.providers.mock_agents import build_panel_revision
from app.providers.mock_llm import MockLLMProvider


@pytest.fixture
def project(settings, story, tmp_path):
    settings.auto_approve = True
    return run_project(new_project(story, "rev", settings), settings=settings, job_dir=tmp_path)


def character_panel(project):
    return next((pg.page_number, pn.panel_number) for pg, pn in project.page_plan.all_panels() if pn.characters)


@pytest.mark.parametrize("instruction, check", [
    ("make her angrier", lambda r: r.emotion == "furious" and "clenched teeth" in r.prompt_add and r.keep_seed),
    ("camera from below", lambda r: r.angle == "low" and "from below" in r.prompt_add and not r.keep_seed),
    ("zoom in on her face", lambda r: r.shot == "close-up" and not r.keep_seed),
    ("add some neon signs", lambda r: r.prompt_add == ["add some neon signs"]),
])
def test_mock_revision_understands_common_notes(instruction, check):
    data = build_panel_revision({"instruction": instruction, "action": "Aya runs", "emotion": "calm",
                                 "shot": "medium", "angle": "eye level", "composition": "centred"})
    assert check(PanelRevision.model_validate(data))


def test_revise_spec_sends_instruction_and_current_spec(project, tmp_path):
    seen = {}

    class Spy(MockLLMProvider):
        def generate_json(self, *, task, context, user, **kw):
            seen.update(task=task, user=user)
            return super().generate_json(task=task, context=context, user=user, **kw)

    page, panel = character_panel(project)
    planned, directed, spec = find_panel(project, page, panel)
    revision, step = revise_spec(project, planned, directed, spec, "make him angrier", Spy())
    assert seen["task"] == "panel_revision" and "make him angrier" in seen["user"] and planned.action in seen["user"]
    assert step.agent == "panel_revision" and revision.emotion == "furious"


def test_apply_revision_updates_plan_director_and_prompt(project, tmp_path):
    page, panel = character_panel(project)
    planned, directed, spec = find_panel(project, page, panel)
    old_seed, name = spec.seed, planned.characters[0]
    bible = project.character(name).tag_prompt()
    revision = PanelRevision(action="She glares, fists clenched", emotion="furious", shot="close-up", angle="low",
                             composition="face fills the frame", prompt_add=["glaring"], negative_add=["smile"],
                             keep_seed=False, summary="angrier, from below")
    draw = apply_revision(project, planned, directed, spec, revision, tmp_path, attempt_hint=2)
    assert planned.action == "She glares, fists clenched" and planned.emotion == "furious"
    assert directed.shot == "close-up" and directed.angle == "low"
    assert "from below" in spec.prompt and "(glaring:1.15)" in spec.prompt
    assert bible in spec.prompt                       # fixed character tags kept
    assert "smile" in spec.negative_prompt
    assert spec.seed != old_seed and draw.seed == spec.seed
    if spec.references:
        assert any(": angry" in k for k in spec.reference_kinds)   # furious -> angry expression reference


def test_keep_seed_keeps_composition(project, tmp_path):
    page, panel = character_panel(project)
    planned, directed, spec = find_panel(project, page, panel)
    seed = spec.seed
    revision = PanelRevision(action=planned.action, emotion="sad", shot=directed.shot, angle=directed.angle,
                             composition=directed.composition, keep_seed=True, summary="sadder")
    assert apply_revision(project, planned, directed, spec, revision, tmp_path, attempt_hint=2).seed == seed


def test_revise_endpoint_redraws_panel_in_a_new_round(settings, story):
    settings.auto_approve = True
    run_project(new_project(story, "rv", settings), settings=settings, job_dir=settings.output_dir / "rv")
    with TestClient(create_app(settings)) as client:
        before = client.get("/api/jobs/rv/project").json()
        page, panel = next((p["page"], p["panel"]) for p in before["prompts"] if p["characters"])
        attempts_before = len(next(r for r in before["panels"] if (r["page"], r["panel"]) == (page, panel))["attempts"])
        response = client.post(f"/api/jobs/rv/panels/{page}/{panel}/revise", json={"instruction": "make her angrier"})
        assert response.status_code == 202 and response.json()["busy"].startswith("Revising")
        # a second action while busy is refused
        assert client.post(f"/api/jobs/rv/panels/{page}/{panel}/revise", json={"instruction": "x y"}).status_code == 409
        for _ in range(100):
            job = client.get("/api/jobs/rv").json()
            if not job["busy"]:
                break
            time.sleep(0.1)
        assert job["status"] == "done" and job["error"] is None
        after = client.get("/api/jobs/rv/project").json()
        result = next(r for r in after["panels"] if (r["page"], r["panel"]) == (page, panel))
        new = [a for a in result["attempts"] if a["round"] == 2]
        assert len(result["attempts"]) > attempts_before and new and new[0]["source"] == "revision"
        assert any(s["agent"] == "panel_revision" for s in after["trace"])
        planned = after["page_plan"]["pages"][page - 1]["panels"][panel - 1]
        assert planned["emotion"] == "furious"
        assert client.post("/api/jobs/rv/panels/1/99/revise", json={"instruction": "abc"}).status_code == 404
