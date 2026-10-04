from PIL import Image

from app.config import Settings
from app.agents.schemas import BeatSheet, CharacterBibleDraft, DirectorPlan, PagePlan
from app.providers import ImageRequest
from app.providers.factory import get_image_provider, get_llm_provider, resolve_image_name, resolve_llm_name
from app.providers.mock_image import MockImageProvider
from app.providers.mock_llm import MockLLMProvider, find_names, split_sentences


def test_auto_mode_without_keys_uses_mocks():
    s = Settings(llm_provider="auto", image_provider="auto")
    assert resolve_llm_name(s) == "mock"
    assert resolve_image_name(s) == "mock"
    assert isinstance(get_llm_provider(s), MockLLMProvider)
    assert isinstance(get_image_provider(s), MockImageProvider)


def test_auto_mode_picks_real_providers_when_configured():
    s = Settings(llm_provider="auto", image_provider="auto",
                 anthropic_api_key="test-key", comfyui_url="http://localhost:8188")
    assert resolve_llm_name(s) == "anthropic"
    assert resolve_image_name(s, probe=lambda url: True) == "comfyui"
    assert resolve_image_name(s, probe=lambda url: False) == "mock"


def test_llm_priority_order():
    s = Settings(gemini_api_key="g", openai_base_url="http://x/v1", openai_api_key="o")
    assert resolve_llm_name(s) == "gemini"
    s.anthropic_api_key = "a"
    assert resolve_llm_name(s) == "anthropic"
    assert resolve_llm_name(Settings(openai_base_url="http://x/v1", openai_api_key="o")) == "openai"


def test_describe_never_contains_secrets():
    s = Settings(anthropic_api_key="sk-secret-value", hosted_image_api_key="other-secret")
    text = str(s.describe())
    assert "sk-secret-value" not in text and "other-secret" not in text


def test_sentence_splitting_keeps_speaker_attribution():
    sentences = split_sentences('"Run!" shouted Ken. The door slammed.')
    assert sentences == ['"Run!" shouted Ken.', "The door slammed."]


def test_find_names(story):
    names = find_names(split_sentences(story))
    assert names[:2] == ["Mira", "Kaito"]


def test_mock_llm_answers_every_agent_task_deterministically(story):
    llm = MockLLMProvider()

    def ask(task, **ctx):
        a = llm.generate_json(system="", user="", schema={}, task=task, context=ctx).data
        b = llm.generate_json(system="", user="", schema={}, task=task, context=ctx).data
        assert a == b
        return a

    sheet = BeatSheet.model_validate(ask("beat_sheet", story=story))
    assert {c.name for c in sheet.characters} >= {"Mira", "Kaito"}
    plan = PagePlan.model_validate(ask("page_plan", story=story, beat_sheet=sheet.model_dump(mode="json")))
    speakers = {line.speaker for _, p in plan.all_panels() for line in p.dialogue}
    assert {"Kaito", "Mira"} <= speakers
    DirectorPlan.model_validate(ask("director", page_plan=plan.model_dump(mode="json"),
                                    beat_sheet=sheet.model_dump(mode="json")))
    bible = CharacterBibleDraft.model_validate(ask("character_bible", beat_sheet=sheet.model_dump(mode="json")))
    assert [c.name for c in bible.characters] == [c.name for c in sheet.characters]


def test_mock_image_draws_character_sheets():
    provider = MockImageProvider()
    sheet = provider.generate(ImageRequest(prompt="x", width=600, height=400, kind="turnaround",
                                           metadata={"name": "Mira"}))
    faces = provider.generate(ImageRequest(prompt="x", width=1000, height=400, kind="expressions",
                                           metadata={"name": "Mira"}))
    assert sheet.size == (600, 400) and faces.size == (1000, 400)
    assert sheet.getextrema()[0] == 0 and faces.getextrema()[0] == 0


def test_mock_image_size_and_determinism():
    provider = MockImageProvider()
    req = ImageRequest(prompt="x", width=400, height=300, seed=7,
                       metadata={"shot": "wide", "characters": ["Mira", "Kaito"], "mood": "dramatic"})
    a, b = provider.generate(req), provider.generate(req)
    assert isinstance(a, Image.Image) and a.size == (400, 300)
    assert a.tobytes() == b.tobytes()
    # It actually drew something (not a blank page)
    assert a.getextrema()[0] == 0
