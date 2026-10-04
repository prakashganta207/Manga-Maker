"""Director agent rules + prompt builder."""

import pytest

from app.agents.director import check_director, direct, enforce_rules, is_peak, shot_runs_ok
from app.agents.prompt_builder import (ANGLE_TAGS, NEGATIVE_PROMPT, SHOT_TAGS, build_prompt, choose_reference,
                                       expression_for, image_size_for_aspect)
from app.agents.schemas import (SHOT_TYPES, BeatSheet, DirectedPage, DirectedPanel, DirectorPlan, PagePlan,
                                PlannedPage, PlannedPanel, VisualTags)
from app.agents.state import CharacterEntry, CharacterSheets, MangaProject
from app.agents.writer import plan_pages, write_beat_sheet
from app.providers.mock_llm import MockLLMProvider


def sheet(intensities, climax):
    return BeatSheet(title="t", logline="l", emotional_arc="a", climax_beat=climax,
                     characters=[{"name": "Aya", "role": "hero"}],
                     beats=[{"id": i + 1, "summary": "s", "emotion": "calm", "intensity": v,
                             "kind": "climax" if i + 1 == climax else "rising"} for i, v in enumerate(intensities)])


def plan_and_direction(settings_list, shots, beats=None, emotions=None):
    """One page per 3 panels; settings_list/shots per panel."""
    planned, directed = [], []
    for i, (setting, shot) in enumerate(zip(settings_list, shots)):
        planned.append(PlannedPanel(panel_number=i + 1, beat=(beats or [1] * len(shots))[i], purpose="p",
                                    size="medium", characters=["Aya"], action="a", setting=setting,
                                    emotion=(emotions or ["calm"] * len(shots))[i]))
        directed.append(DirectedPanel(panel_number=i + 1, shot=shot, angle="eye level", composition="c"))
    page_plan = PagePlan(pages=[PlannedPage(page_number=1, panels=planned)])
    plan = DirectorPlan(pages=[DirectedPage(page_number=1, layout="grid_6", panels=directed)])
    return page_plan, plan


def shots(plan):
    return [p.shot for page in plan.pages for p in page.panels]


# --------------------------------------------------------------------------- rules
def test_establishing_shot_when_setting_changes():
    page_plan, plan = plan_and_direction(["a park", "the park", "a school roof", "a school roof"],
                                         ["medium", "close-up", "medium", "close-up"])
    fixes = enforce_rules(plan, page_plan, sheet([1, 2], 2))
    s = shots(plan)
    assert s[0] == "establishing"          # first panel = new setting
    assert s[1] != "establishing"          # "a park" == "the park" (articles ignored)
    assert s[2] == "establishing"          # school roof
    assert any("setting changes" in f for f in fixes)


def test_close_up_on_emotional_peak():
    page_plan, plan = plan_and_direction(["park"] * 4, ["establishing", "medium", "wide", "medium"],
                                         beats=[1, 1, 2, 2])
    fixes = enforce_rules(plan, page_plan, sheet([1, 5], 2))
    s = shots(plan)
    assert s[3] in ("close-up", "extreme close-up")
    assert any("emotional peak" in f for f in fixes)


def test_peak_already_close_is_left_alone():
    page_plan, plan = plan_and_direction(["park"] * 3, ["establishing", "extreme close-up", "medium"],
                                         beats=[1, 2, 2])
    fixes = enforce_rules(plan, page_plan, sheet([1, 5], 2))
    assert shots(plan)[1] == "extreme close-up" and not any("peak" in f for f in fixes)


def test_no_more_than_two_identical_shots_in_a_row():
    page_plan, plan = plan_and_direction(["park"] * 6, ["establishing"] + ["medium"] * 5)
    enforce_rules(plan, page_plan, sheet([1, 2], 2))
    assert shot_runs_ok(plan)


def test_variety_fix_keeps_peak_panels_close():
    # Three peak close-ups in a row: the fix may only swap to another *close* shot.
    page_plan, plan = plan_and_direction(["park"] * 4, ["establishing", "close-up", "close-up", "close-up"],
                                         beats=[1, 2, 2, 2])
    enforce_rules(plan, page_plan, sheet([1, 5], 2))
    s = shots(plan)
    assert shot_runs_ok(plan) and all(x in ("close-up", "extreme close-up") for x in s[1:])


def test_is_peak():
    s = sheet([1, 4, 5], 3)
    panel = lambda beat, emotion: PlannedPanel(panel_number=1, beat=beat, purpose="p", size="medium",  # noqa: E731
                                               action="a", setting="s", emotion=emotion)
    assert is_peak(panel(3, "calm"), s)            # climax
    assert is_peak(panel(2, "grief"), s)           # intense + emotional
    assert not is_peak(panel(1, "grief"), s)       # not intense enough


def test_check_director_layout_must_fit():
    page_plan, plan = plan_and_direction(["park"] * 3, ["establishing", "medium", "close-up"])
    plan.pages[0].layout = "grid_6"
    assert any("6 slots" in p for p in check_director(plan, page_plan))
    plan.pages[0].layout = "nope"
    assert any("unknown layout" in p for p in check_director(plan, page_plan))
    plan.pages[0].layout = "three_tier"
    assert check_director(plan, page_plan) == []


@pytest.mark.parametrize("story_fixture", ["story"])
def test_mock_director_end_to_end(story_fixture, request):
    story = request.getfixturevalue(story_fixture)
    project = MangaProject(job_id="j", project_id="p", story=story)
    llm = MockLLMProvider()
    write_beat_sheet(project, llm)
    plan_pages(project, llm)
    step = direct(project, llm)
    assert step.status == "ok" and check_director(project.director, project.page_plan) == []
    assert shot_runs_ok(project.director)
    first = project.director.pages[0].panels[0]
    assert first.shot == "establishing"
    assert all(p.shot in SHOT_TYPES for page in project.director.pages for p in page.panels)


# --------------------------------------------------------------------------- prompt builder
def entry(name="Aya", sheets=None):
    return CharacterEntry(name=name, role="hero", age_range="teens", body_type="slim", description="d",
                          personality="p", visual_tags=VisualTags(hair="short black bob", eyes="sharp eyes",
                                                                  outfit="sailor uniform", accessories="red scarf"),
                          sheets=sheets or CharacterSheets())


def test_prompt_has_style_shot_angle_and_exact_tags():
    panel = PlannedPanel(panel_number=1, beat=1, purpose="p", size="medium", characters=["Aya"],
                         action="Aya grips the railing.", setting="a rooftop", emotion="shock")
    direction = DirectedPanel(panel_number=1, shot="close-up", angle="low", composition="Aya off-centre right.")
    prompt = build_prompt(panel, direction, {"aya": entry()})
    assert prompt.startswith("monochrome, greyscale, manga")
    assert SHOT_TAGS["close-up"] in prompt and ANGLE_TAGS["low"] in prompt
    assert "short black bob, sharp eyes, sailor uniform, red scarf" in prompt
    assert "surprised, wide eyes" in prompt          # shock -> surprised expression
    assert "solo" in prompt and "setting: a rooftop" in prompt
    assert "color" in NEGATIVE_PROMPT and "speech bubble" in NEGATIVE_PROMPT


def test_every_shot_and_angle_has_tags():
    assert set(SHOT_TAGS) == set(SHOT_TYPES)
    assert set(ANGLE_TAGS) == {"eye level", "low", "high", "bird's eye"}


def test_expression_mapping():
    assert expression_for("joyful relief") == "happy"
    assert expression_for("grief") == "sad"
    assert expression_for("furious") == "angry"
    assert expression_for("shocked") == "surprised"
    assert expression_for("pensive") == "neutral"


def test_choose_reference_prefers_matching_expression():
    sheets = CharacterSheets(turnaround="t.png", views={"front": "front.png"},
                             expression_refs={"happy": "happy.png", "neutral": "neutral.png"})
    assert choose_reference(entry(sheets=sheets), "joy") == ("happy.png", "happy")
    assert choose_reference(entry(sheets=sheets), "rage") == ("front.png", "front")
    assert choose_reference(entry(), "joy") == (None, "")


def test_image_size_for_aspect():
    assert image_size_for_aspect(832 / 1216, 1008) == (832, 1216)
    w, h = image_size_for_aspect(3.0, 1008)
    assert w % 64 == 0 and h % 64 == 0 and w <= 1536 and h >= 512
