import json

from PIL import Image

from app.models import Panel
from app.pipeline.characters import build_character_sheets, slugify
from app.pipeline.panels import generate_panel_images, panel_seed
from app.pipeline.prompts import (NEGATIVE_PROMPT, STYLE_PROMPT, build_panel_prompt,
                                  build_panel_request, image_size_for_aspect)
from app.pipeline.script import generate_script
from app.providers.mock_image import MockImageProvider
from app.providers.mock_llm import MockLLMProvider


def make_script(story):
    script, _ = generate_script(story, MockLLMProvider())
    return script


def test_character_sheets_and_reference_images(story, tmp_path):
    script = make_script(story)
    sheets = build_character_sheets(script, MockImageProvider(), tmp_path, reference_size=256)
    assert [s.name for s in sheets] == [c.name for c in script.characters]
    for sheet in sheets:
        assert sheet.hair in sheet.prompt_description and sheet.outfit in sheet.prompt_description
        image = Image.open(tmp_path / sheet.reference_image)
        assert image.size == (256, 256)
    saved = json.loads((tmp_path / "characters" / "sheets.json").read_text())
    assert saved[0]["name"] == sheets[0].name


def test_sheets_without_image_provider(story, tmp_path):
    sheets = build_character_sheets(make_script(story), None, tmp_path)
    assert all(s.reference_image is None for s in sheets)


def test_same_description_reused_in_every_panel(story, tmp_path):
    script = make_script(story)
    sheets = {s.name.lower(): s for s in build_character_sheets(script, None, tmp_path)}
    for _, panel in script.all_panels():
        prompt = build_panel_prompt(panel, sheets)
        for name in panel.characters:
            assert sheets[name.lower()].prompt_description in prompt
        assert STYLE_PROMPT in prompt


def test_prompt_mentions_shot_and_never_asks_for_text():
    panel = Panel(panel_number=1, characters=[], action="An empty street at dawn",
                  setting="a city street", shot="wide", mood="calm")
    prompt = build_panel_prompt(panel, {})
    assert prompt.startswith("wide establishing shot")
    assert "scenery only" in prompt
    assert "speech bubble" in NEGATIVE_PROMPT and "color" in NEGATIVE_PROMPT


def test_image_size_for_aspect():
    w, h = image_size_for_aspect(2.0, 832)
    assert w % 64 == 0 and h % 64 == 0
    assert 1.7 < w / h < 2.3
    assert image_size_for_aspect(1.0, 512) == (512, 512)


def test_panel_request_includes_reference_images(story, tmp_path):
    script = make_script(story)
    sheets = {s.name.lower(): s for s in build_character_sheets(script, MockImageProvider(), tmp_path, reference_size=128)}
    _, panel = script.all_panels()[0]
    request = build_panel_request(panel, sheets, page_number=1, aspect=1.5, seed=3, job_dir=tmp_path)
    assert request.width > request.height
    assert len(request.reference_images) == len(panel.characters)
    assert all(p.exists() for p in request.reference_images)


def test_generate_panel_images(story, tmp_path):
    script = make_script(story)
    sheets = build_character_sheets(script, None, tmp_path)
    seen = []
    results = generate_panel_images(script, sheets, MockImageProvider(), tmp_path, base_size=256,
                                    aspects={(1, 1): 2.0}, on_progress=lambda d, t, m: seen.append(d))
    assert len(results) == len(script.all_panels()) == len(seen)
    first = Image.open(results[(1, 1)])
    assert first.width > first.height
    log = json.loads((tmp_path / "panels" / "prompts.json").read_text())
    assert len(log) == len(results)
    assert panel_seed(5, 1, 2) != panel_seed(5, 1, 3)


def test_slugify():
    assert slugify("Mira Tanaka!") == "mira-tanaka"
    assert slugify("???") == "character"
