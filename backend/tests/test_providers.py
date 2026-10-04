from PIL import Image

from app.config import Settings
from app.models import MangaScript
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
    assert resolve_image_name(s) == "comfyui"


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


def test_mock_llm_is_deterministic_and_valid(story):
    llm = MockLLMProvider()
    ctx = {"story": story, "panels_per_page": 4, "max_pages": 2}
    a = llm.generate_json(system="", user="", schema={}, task="manga_script", context=ctx)
    b = llm.generate_json(system="", user="", schema={}, task="manga_script", context=ctx)
    assert a == b
    script = MangaScript.model_validate(a)
    assert len(script.pages[0].panels) == 4
    assert {c.name for c in script.characters} >= {"Mira", "Kaito"}
    speakers = {line.speaker for _, p in script.all_panels() for line in p.dialogue}
    assert "Kaito" in speakers and "Mira" in speakers


def test_mock_image_size_and_determinism():
    provider = MockImageProvider()
    req = ImageRequest(prompt="x", width=400, height=300, seed=7,
                       metadata={"shot": "wide", "characters": ["Mira", "Kaito"], "mood": "dramatic"})
    a, b = provider.generate(req), provider.generate(req)
    assert isinstance(a, Image.Image) and a.size == (400, 300)
    assert a.tobytes() == b.tobytes()
    # It actually drew something (not a blank page)
    assert a.getextrema()[0] == 0
