import json

import pytest
from pydantic import ValidationError

from app.models import MangaScript, Panel
from app.pipeline.script import ScriptError, build_user_prompt, generate_script
from app.providers.base import LLMProvider
from app.providers.mock_llm import MockLLMProvider


class FakeLLM(LLMProvider):
    """Returns canned answers in order and records the prompts it received."""

    name = "fake"

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def generate_json(self, *, system, user, schema, task, context):
        self.prompts.append(user)
        return self.answers.pop(0)


def good_script(**overrides):
    data = {
        "title": "Test",
        "characters": [{"name": "Aya", "hair": "short black hair", "outfit": "school uniform",
                        "features": "freckles"}],
        "pages": [{"page_number": 1, "panels": [
            {"panel_number": n, "characters": ["Aya"], "action": f"Aya does thing {n}",
             "setting": "a park", "shot": "medium", "mood": "calm",
             "dialogue": [{"speaker": "Aya", "text": "Hello."}], "narration": None}
            for n in range(1, 5)]}],
    }
    data.update(overrides)
    return data


def test_mock_script_is_valid(story):
    script, warnings = generate_script(story, MockLLMProvider(), panels_per_page=4, max_pages=2)
    assert isinstance(script, MangaScript)
    assert warnings == []
    assert len(script.pages[0].panels) == 4
    for page in script.pages:
        assert [p.panel_number for p in page.panels] == list(range(1, len(page.panels) + 1))


def test_retry_with_validation_feedback():
    bad = good_script()
    bad["pages"][0]["panels"][0]["shot"] = "bird's eye"
    llm = FakeLLM([bad, good_script()])
    script, _ = generate_script("A story.", llm)
    assert script.title == "Test"
    assert len(llm.prompts) == 2
    assert "rejected by the validator" in llm.prompts[1]
    assert "shot" in llm.prompts[1]


def test_accepts_json_string_with_code_fence():
    llm = FakeLLM(["```json\n" + json.dumps(good_script()) + "\n```"])
    script, _ = generate_script("A story.", llm)
    assert script.characters[0].name == "Aya"


def test_gives_up_after_max_attempts():
    llm = FakeLLM(["not json", "still not json", "{}"])
    with pytest.raises(ScriptError):
        generate_script("A story.", llm, max_attempts=3)


def test_empty_story_rejected():
    with pytest.raises(ScriptError):
        generate_script("   ", MockLLMProvider())


def test_unknown_speaker_fails_validation():
    data = good_script()
    data["pages"][0]["panels"][0]["dialogue"] = [{"speaker": "Ghost", "text": "Boo"}]
    with pytest.raises(ValidationError):
        MangaScript.model_validate(data)


def test_shot_spelling_is_normalised():
    panel = Panel(panel_number=1, action="x", setting="y", shot="Close Up", mood="calm")
    assert panel.shot == "close-up"


def test_copyrighted_names_are_replaced():
    data = good_script()
    data["characters"][0]["name"] = "Pikachu"
    for panel in data["pages"][0]["panels"]:
        panel["characters"] = ["Pikachu"]
        panel["dialogue"] = [{"speaker": "pikachu", "text": "Hi"}]
    script, warnings = generate_script("A story.", FakeLLM([data]))
    assert warnings and "Pikachu" in warnings[0]
    names = {c.name for c in script.characters}
    assert "Pikachu" not in names
    panel = script.pages[0].panels[0]
    assert panel.characters == ["Original A"] and panel.dialogue[0].speaker == "Original A"


def test_extra_pages_and_numbers_are_normalised():
    data = good_script()
    page = data["pages"][0]
    data["pages"] = [dict(page, page_number=5), dict(page, page_number=9), dict(page, page_number=9)]
    for i, p in enumerate(page["panels"]):
        p["panel_number"] = 10 + i
    script, _ = generate_script("A story.", FakeLLM([data]), max_pages=2)
    assert [p.page_number for p in script.pages] == [1, 2]
    assert [p.panel_number for p in script.pages[0].panels] == [1, 2, 3, 4]


def test_user_prompt_contains_story_and_limits():
    prompt = build_user_prompt("Once upon a time.", 4, 2)
    assert "Once upon a time." in prompt and "4 panels" in prompt
