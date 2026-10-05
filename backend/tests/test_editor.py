"""Phase 3 M1: Editor schema, vision requests, score combination and fix application."""

import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.agents.editor import review_images, review_panel, system_prompt
from app.agents.quality import (QualityConfig, apply_fix, apply_prompt_fix, clip_score, combine, editor_score,
                                split_tags)
from app.agents.schemas import EDITOR_CRITERIA, DirectedPanel, EditorFix, EditorReview, PlannedPanel
from app.agents.state import MangaProject, PanelPrompt
from app.config import Settings
from app.providers.anthropic_llm import AnthropicLLMProvider
from app.providers.base import ImageInput
from app.providers.gemini_llm import GeminiLLMProvider
from app.providers.mock_agents import build_editor_review
from app.providers.mock_llm import MockLLMProvider
from app.providers.openai_compat_llm import OpenAICompatibleLLMProvider


def scores(**overrides):
    base = {name: 4 for name in EDITOR_CRITERIA}
    return {**base, **overrides}


def review(verdict="pass", problems=None, fix=None, **score_overrides) -> EditorReview:
    return EditorReview.model_validate({"scores": scores(**score_overrides), "verdict": verdict,
                                        "problems": problems or [], "fix": fix or {}, "reasoning": "ok"})


# --------------------------------------------------------------------------- schema
def test_review_schema_accepts_valid_answer():
    r = review()
    assert r.scores.as_dict()["anatomy"] == 4
    assert r.fix.is_empty()


@pytest.mark.parametrize("bad", [
    {"scores": scores(anatomy=6)},                       # out of range
    {"scores": scores(anatomy=0)},
    {"scores": {k: 4 for k in list(EDITOR_CRITERIA)[:-1]}},  # missing a criterion
    {"verdict": "maybe"},
    {"verdict": "fail", "problems": []},                 # fail needs problems ...
    {"verdict": "fail", "problems": ["bad hand"], "fix": {}},  # ... and a concrete fix
    {"fix": {"ipadapter_weight": 2.0}},
    {"reasoning": ""},
])
def test_review_schema_rejects_bad_answers(bad):
    data = {"scores": scores(), "verdict": "pass", "problems": [], "fix": {}, "reasoning": "ok", **bad}
    with pytest.raises(ValidationError):
        EditorReview.model_validate(data)


def test_review_schema_normalises_verdict_and_tags():
    r = EditorReview.model_validate({"scores": scores(), "verdict": " FAIL ", "problems": ["x"],
                                     "fix": {"prompt_add": ["  from   below ", "", "a, b"]}, "reasoning": "r"})
    assert r.verdict == "fail"
    assert r.fix.prompt_add == ["from below", "a b"]


def test_system_prompt_lists_every_criterion():
    text = system_prompt()
    assert all(name in text for name in EDITOR_CRITERIA)


# --------------------------------------------------------------------------- threshold logic
CFG = QualityConfig(threshold=0.65, editor_weight=0.7, min_criterion=2, clip_low=0.6, clip_high=0.9)


def test_editor_score_scale():
    assert editor_score(review()) == 0.75
    assert editor_score(review(**{k: 5 for k in EDITOR_CRITERIA})) == 1.0
    assert editor_score(review(**{k: 1 for k in EDITOR_CRITERIA}, verdict="pass")) == 0.0


def test_clip_rescaled_and_weakest_character_counts():
    assert clip_score({}, CFG) is None
    assert clip_score({"Aya": 0.9, "Ken": 0.75}, CFG) == 0.5
    assert clip_score({"Aya": 0.5}, CFG) == 0.0
    assert clip_score({"Aya": 0.99}, CFG) == 1.0


def test_combine_passes_good_panel():
    q = combine(review(), {"Aya": 0.84}, CFG)
    assert q.passed and q.reasons == []
    assert q.combined == pytest.approx(0.7 * 0.75 + 0.3 * 0.8)


def test_combine_without_characters_uses_editor_only():
    q = combine(review(), {}, CFG)
    assert q.clip is None and q.combined == 0.75 and q.passed


def test_combine_fails_on_low_clip_even_if_editor_happy():
    q = combine(review(), {"Aya": 0.55}, CFG)  # character drifted
    assert not q.passed
    assert any("threshold" in r for r in q.reasons)


def test_combine_fails_on_single_deal_breaker():
    q = combine(review(**{**{k: 5 for k in EDITOR_CRITERIA}, "anatomy": 2}), {"Aya": 0.9}, CFG)
    assert q.combined > CFG.threshold
    assert not q.passed and any("anatomy" in r for r in q.reasons)


def test_combine_respects_editor_verdict():
    q = combine(review(verdict="fail", problems=["off"], fix={"new_seed": True}), {"Aya": 0.9}, CFG)
    assert not q.passed and "Editor verdict: fail" in q.reasons


def test_threshold_is_configurable():
    strict = QualityConfig(threshold=0.9)
    assert not combine(review(), {}, strict).passed
    lenient = QualityConfig(threshold=0.5, min_criterion=1)
    assert combine(review(anatomy=2), {}, lenient).passed


def test_unreviewed_panel_never_passes():
    q = combine(None, {"Aya": 0.95}, CFG)
    assert not q.passed and q.editor is None and q.combined == 1.0


# --------------------------------------------------------------------------- fixes
PROMPT = ("monochrome, greyscale, manga, comic panel, close-up, eye level, solo, "
          "(short black hair, narrow eyes, school uniform, smile, happy), she laughs, setting: a rooftop")


def test_split_tags_keeps_character_groups():
    tags = split_tags(PROMPT)
    assert "(short black hair, narrow eyes, school uniform, smile, happy)" in tags
    assert tags[0] == "monochrome"


def test_prompt_fix_adds_after_character_and_never_removes_bible_tags():
    fix = EditorFix(prompt_add=["from below", "close-up"], prompt_remove=["eye level", "short black hair"])
    out = apply_prompt_fix(PROMPT, fix)
    tags = split_tags(out)
    assert "eye level" not in tags
    assert "(from below:1.15)" in tags
    assert "(close-up:1.15)" not in tags  # already present
    group = tags.index("(short black hair, narrow eyes, school uniform, smile, happy)")
    assert tags[group + 1] == "(from below:1.15)"


def test_apply_fix_changes_seed_weight_and_negative():
    fix = EditorFix(negative_add=["extra fingers", "color"], ipadapter_weight=1.2, new_seed=True)
    spec = apply_fix(PROMPT, "color, text", 42, 0.7, fix, attempt=2)
    assert spec.negative_prompt == "color, text, extra fingers"
    assert spec.ipadapter_weight == 1.0  # clamped
    assert spec.seed != 42
    assert len(spec.notes) == 3


def test_apply_fix_new_seed_when_nothing_else_changes():
    spec = apply_fix(PROMPT, "x", 42, None, EditorFix(ipadapter_weight=0.9), attempt=2)
    assert spec.ipadapter_weight is None  # no references -> weight is meaningless
    assert spec.seed != 42


def test_apply_fix_respects_seed_lock():
    spec = apply_fix(PROMPT, "x", 42, 0.7, EditorFix(new_seed=True), attempt=2, seed_locked=True)
    assert spec.seed == 42


# --------------------------------------------------------------------------- mock editor
def test_mock_editor_is_deterministic_and_valid(tmp_path):
    path = tmp_path / "p.png"
    Image.new("L", (64, 64), 200).save(path)
    results = []
    for seed in range(40):
        ctx = {"seed": seed, "image_prompt_used": "x", "page": 1, "panel": 1, "attempt": 1, "image_path": str(path)}
        data = build_editor_review(ctx)
        assert data == build_editor_review(ctx)
        results.append(EditorReview.model_validate(data))
    fails = [r for r in results if r.verdict == "fail"]
    assert 0 < len(fails) < len(results)
    assert all(not r.fix.is_empty() for r in fails)


def test_mock_editor_flags_colour(tmp_path):
    path = tmp_path / "c.png"
    Image.new("RGB", (64, 64), (220, 30, 30)).save(path)
    data = build_editor_review({"seed": 1, "image_prompt_used": "colour", "page": 1, "panel": 1, "image_path": str(path)})
    assert data["scores"]["manga_style"] == 2 and data["verdict"] == "fail"
    assert "color" in data["fix"]["negative_add"]


# --------------------------------------------------------------------------- the agent + vision requests
def make_case(tmp_path):
    job = tmp_path / "job"
    (job / "panels").mkdir(parents=True)
    (job / "refs").mkdir()
    Image.new("L", (300, 400), 230).save(job / "panels" / "p.png")
    Image.new("L", (200, 200), 100).save(job / "refs" / "aya.png")
    project = MangaProject(job_id="j", project_id="j", story="Aya runs.")
    spec = PanelPrompt(page=1, panel=2, prompt=PROMPT, negative_prompt="color", seed=7, width=832, height=1216,
                       characters=["Aya"], references=["refs/aya.png", "refs/missing.png"],
                       reference_kinds=["Aya: happy", "Ken: front"])
    planned = PlannedPanel(panel_number=2, beat=1, purpose="p", size="medium", characters=["Aya"],
                           action="Aya laughs", setting="rooftop", emotion="happy")
    directed = DirectedPanel(panel_number=2, shot="close-up", angle="eye level", composition="centred")
    return job, project, spec, planned, directed


def test_review_images_panel_first_and_skip_missing(tmp_path):
    job, _, spec, _, _ = make_case(tmp_path)
    images = review_images(job, job / "panels" / "p.png", spec)
    assert [i.label for i in images] == ["the panel to review", "reference for Aya: happy"]


def test_review_panel_with_mock_records_step(tmp_path):
    job, project, spec, planned, directed = make_case(tmp_path)
    result, step = review_panel(project=project, spec=spec, planned=planned, directed=directed,
                                image=job / "panels" / "p.png", job_dir=job, attempt=1, prompt=spec.prompt,
                                consistency={"Aya": 0.8}, llm=MockLLMProvider())
    assert isinstance(result, EditorReview)
    assert step.agent == "editor" and step.inputs["images"] == 2


def test_anthropic_vision_request_has_labelled_images(tmp_path):
    job, project, spec, planned, directed = make_case(tmp_path)
    answer = build_editor_review({"seed": 1, "page": 1, "panel": 2, "image_prompt_used": "", "image_path": ""})
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=400),
                               content=[SimpleNamespace(type="text", text=json.dumps(answer))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    provider = AnthropicLLMProvider(Settings(anthropic_api_key="x"), client=client)
    _, step = review_panel(project=project, spec=spec, planned=planned, directed=directed,
                           image=job / "panels" / "p.png", job_dir=job, attempt=1, prompt=spec.prompt,
                           consistency={}, llm=provider)
    content = calls[0]["messages"][0]["content"]
    kinds = [b["type"] for b in content]
    assert kinds == ["text", "image", "text", "image", "text"]
    assert content[0]["text"] == "Image 1: the panel to review"
    assert content[1]["source"]["media_type"] == "image/jpeg"
    assert "panel_spec" in content[-1]["text"]
    assert step.cost_usd > 0


def test_openai_and_gemini_vision_payloads(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (2000, 1000), "white").save(path)
    images = [ImageInput(path, "the panel")]
    content = OpenAICompatibleLLMProvider.user_content("question", images)
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert content[-1] == {"type": "text", "text": "question"}
    parts = GeminiLLMProvider.image_parts(images)
    assert parts[0] == {"text": "Image 1: the panel"} and parts[1]["inline_data"]["mime_type"] == "image/jpeg"


def test_gemini_fallback_rewrites_question_part_not_image(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (64, 64), "white").save(path)
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(400, json={"error": "schema"})
        text = json.dumps(build_editor_review({"seed": 3, "page": 1, "panel": 1, "image_prompt_used": "",
                                               "image_path": ""}))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    provider = GeminiLLMProvider(Settings(gemini_api_key="k"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.generate_json(system="s", user="Q", schema=EditorReview.model_json_schema(), task="t", context={},
                           images=[ImageInput(path, "the panel")])
    parts = bodies[1]["contents"][0]["parts"]
    assert "inline_data" in parts[1]
    assert parts[-1]["text"].startswith("Q\n\nAnswer with JSON")
