"""Phase 3 M2: the redraw loop — retries, budgets, best attempt, statuses (mocked Editor)."""

import pytest

from app.agents.pipeline import manifest, new_project, run_project
from app.agents.quality import best_attempt
from app.agents.schemas import EDITOR_CRITERIA, EditorReview
from app.agents.state import PanelAttempt, QualityScore
from app.providers.base import LLMResponse, ProviderError
from app.providers.mock_llm import MockLLMProvider


def answer(verdict="pass", low=None, fix=None, problems=None):
    scores = {k: 4 for k in EDITOR_CRITERIA}
    if low:
        scores[low] = 2
    return {"scores": scores, "verdict": verdict, "problems": problems or (["bad"] if verdict == "fail" else []),
            "fix": fix or ({"new_seed": True} if verdict == "fail" else {}), "reasoning": "scripted"}


class ScriptedEditor(MockLLMProvider):
    """Mock LLM whose Editor answers come from `script(context) -> dict | Exception`."""

    def __init__(self, script):
        self.script = script
        self.reviews = []

    def generate_json(self, *, task, context, **kwargs):
        if task != "editor_review":
            return super().generate_json(task=task, context=context, **kwargs)
        self.reviews.append(context)
        result = self.script(context)
        if isinstance(result, Exception):
            raise result
        return LLMResponse(result, model="mock")


def run(story, settings, tmp_path, llm):
    settings.auto_approve = True
    return run_project(new_project(story, "job", settings), settings=settings, job_dir=tmp_path, llm=llm)


def test_all_pass_first_time(story, settings, tmp_path):
    llm = ScriptedEditor(lambda ctx: answer())
    project = run(story, settings, tmp_path, llm)
    assert project.status == "done"
    assert all(r.status == "accepted" and len(r.attempts) == 1 for r in project.panels)
    assert len(llm.reviews) == len(project.panels)
    assert all(r.attempts[0].status == "accepted" and r.attempts[0].review for r in project.panels)


def test_failed_panel_is_redrawn_with_the_fix(story, settings, tmp_path):
    def script(ctx):
        if (ctx["page"], ctx["panel"]) == (1, 1) and ctx["attempt"] == 1:
            return answer("fail", low="anatomy", fix={"negative_add": ["extra fingers"], "prompt_add": ["from below"],
                                                      "new_seed": True}, problems=["six fingers"])
        return answer()

    project = run(story, settings, tmp_path, ScriptedEditor(script))
    result = project.panel_result(1, 1)
    assert [a.status for a in result.attempts] == ["rejected", "accepted"]
    first, second = result.attempts
    assert second.source == "redraw" and second.fix_applied.negative_add == ["extra fingers"]
    assert "extra fingers" in second.negative_prompt and "(from below:1.15)" in second.prompt
    assert second.seed != first.seed
    assert result.image == second.image and result.chosen_attempt == 2 and result.status == "accepted"
    assert (tmp_path / first.image).exists() and (tmp_path / second.image).exists()  # every attempt kept
    assert project.budget.redraws == 1


def test_max_attempts_then_best_attempt_needs_review(story, settings, tmp_path):
    settings.editor_max_attempts = 3

    def script(ctx):
        if (ctx["page"], ctx["panel"]) != (1, 2):
            return answer()
        # attempt 2 is the best of three failures (only one low criterion, no verdict pass)
        lows = {1: ["anatomy", "emotion"], 2: ["anatomy"], 3: ["anatomy", "shot_angle"]}[ctx["attempt"]]
        data = answer("fail")
        for low in lows:
            data["scores"][low] = 1
        return data

    project = run(story, settings, tmp_path, ScriptedEditor(script))
    result = project.panel_result(1, 2)
    assert len(result.attempts) == 3
    assert result.status == "needs_review" and result.chosen_attempt == 2
    assert [a.status for a in result.attempts] == ["rejected", "needs_review", "rejected"]
    assert "3 attempts" in result.review_note
    assert manifest(project)["quality"]["needs_review"] == 1


def test_llm_call_budget_stops_redraws(story, settings, tmp_path):
    llm = ScriptedEditor(lambda ctx: answer("fail", low="anatomy"))
    settings.job_max_llm_calls = 6   # 4 planning agents + 2 reviews
    project = run(story, settings, tmp_path, llm)
    assert project.status == "done"
    assert project.budget.exhausted and "LLM call budget" in project.budget.exhausted
    assert len(llm.reviews) == 2
    first = project.panels[0]
    assert len(first.attempts) == 2 and first.status == "needs_review"   # one redraw, then the budget ran out
    assert "LLM call budget" in first.review_note
    assert all(len(r.attempts) == 1 for r in project.panels[1:])   # no more redraws once the budget is gone
    unreviewed = [r for r in project.panels if r.status == "unreviewed"]
    assert unreviewed and "budget" in unreviewed[0].attempts[0].note
    assert any("Budget limit" in w for w in project.warnings)


def test_gpu_budget_stops_redraws(story, settings, tmp_path):
    settings.job_max_gpu_seconds = 1e-9   # the sheets alone use it up
    llm = ScriptedEditor(lambda ctx: answer("fail", low="anatomy"))
    project = run(story, settings, tmp_path, llm)
    assert "GPU time budget" in project.budget.exhausted
    assert all(len(r.attempts) == 1 for r in project.panels)


def test_editor_disabled_draws_once(story, settings, tmp_path):
    settings.editor_enabled = False
    llm = ScriptedEditor(lambda ctx: pytest.fail("Editor must not be called"))
    project = run(story, settings, tmp_path, llm)
    assert all(r.status == "unreviewed" and len(r.attempts) == 1 for r in project.panels)


def test_editor_errors_do_not_break_the_job(story, settings, tmp_path):
    project = run(story, settings, tmp_path, ScriptedEditor(lambda ctx: ProviderError("vision down")))
    assert project.status == "done"
    assert all(r.status == "unreviewed" for r in project.panels)
    assert any(s.agent == "editor" and s.status == "failed" for s in project.trace)


def test_invalid_editor_json_is_retried_then_accepted(story, settings, tmp_path):
    calls = {"n": 0}

    def script(ctx):
        calls["n"] += 1
        return {"scores": {"anatomy": 9}} if calls["n"] == 1 else answer()

    project = run(story, settings, tmp_path, ScriptedEditor(script))
    first_review = next(s for s in project.trace if s.agent == "editor")
    assert first_review.attempts == 2 and first_review.errors
    assert project.panels[0].status == "accepted"


def test_budget_counts_llm_calls_and_images(story, settings, tmp_path):
    project = run(story, settings, tmp_path, ScriptedEditor(lambda ctx: answer()))
    assert project.budget.llm_calls == sum(s.attempts for s in project.trace)
    assert project.budget.images >= len(project.panels)
    assert project.budget.limits["max_attempts"] == settings.editor_max_attempts
    quality = manifest(project)["quality"]
    assert quality["accepted"] == len(project.panels) and quality["cost_per_page_usd"] == 0.0


def test_resume_redraws_an_interrupted_panel(story, settings, tmp_path):
    project = run(story, settings, tmp_path, ScriptedEditor(lambda ctx: answer()))
    result = project.panel_result(1, 1)
    result.status = "drawing"   # as if the process died inside the loop
    project.status = "running"
    project.save(tmp_path)
    resumed = run_project(project, settings=settings, job_dir=tmp_path, llm=ScriptedEditor(lambda ctx: answer()))
    again = resumed.panel_result(1, 1)
    assert again.status == "accepted" and len(again.attempts) == 2 and again.attempts[1].round == 2
    assert all(len(r.attempts) == 1 for r in resumed.panels if (r.page, r.panel) != (1, 1))


def test_default_mock_editor_exercises_the_loop(story, settings, tmp_path):
    project = run(story, settings, tmp_path, MockLLMProvider())
    attempts = [a for r in project.panels for a in r.attempts]
    assert project.status == "done"
    assert any(a.status == "rejected" for a in attempts)     # some redraws happened
    assert all(r.status in ("accepted", "needs_review") for r in project.panels)
    for r in project.panels:
        EditorReview.model_validate(r.attempts[-1].review.model_dump())


# --------------------------------------------------------------------------- best attempt selection
def att(n, combined, passed=False, problems=1):
    review = EditorReview.model_validate(answer("fail" if problems else "pass",
                                                problems=["p"] * problems if problems else None))
    return PanelAttempt(attempt=n, image=f"{n}.png", review=review,
                        quality=QualityScore(combined=combined, passed=passed))


def test_best_attempt_prefers_passed_then_score_then_fewer_problems_then_latest():
    assert best_attempt([att(1, 0.9), att(2, 0.7, passed=True, problems=0)]).attempt == 2
    assert best_attempt([att(1, 0.5), att(2, 0.6), att(3, 0.55)]).attempt == 2
    assert best_attempt([att(1, 0.6, problems=3), att(2, 0.6, problems=1)]).attempt == 2
    assert best_attempt([att(1, 0.6), att(2, 0.6)]).attempt == 2
    unreviewed = PanelAttempt(attempt=3, image="3.png")
    assert best_attempt([unreviewed, att(1, 0.1)]).attempt == 1
    with pytest.raises(ValueError):
        best_attempt([])
