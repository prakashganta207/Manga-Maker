"""Phase 3-5 integration tests with REAL services. Each one skips itself when what it needs is missing:

    - ComfyUI reachable at COMFYUI_URL           (inpainting, Letterer on real art, storyboard, chapters)
    - an LLM key (Anthropic / Gemini / OpenAI)    (a real vision Editor; otherwise the mock Editor reviews
                                                    real images)
    - kohya-ss sd-scripts in tools/sd-scripts     (LoRA training; slow: ~20 min on an 8 GB GPU, so it also
                                                    needs RUN_LORA_TRAINING=1)

    cd backend && .venv/Scripts/python -m pytest tests/test_integration_phase5.py -s

Outputs go to samples/integration_output/phase5/ (git-ignored).
"""

import os
import shutil

import pytest
from PIL import Image, ImageChops, ImageDraw

from app.agents.graph import Ctx
from app.agents.inpaint import inpaint_panel
from app.agents.pipeline import new_project, run_project
from app.agents.revision import revise_panel
from app.config import REPO_DIR
from app.providers import get_image_provider, get_llm_provider
from app.providers.factory import comfyui_reachable, resolve_llm_name
from app.training.lora import kohya_available
from tests.test_integration import real_settings

SETTINGS = real_settings()
HAS_COMFY = SETTINGS.image_provider in ("auto", "comfyui") and comfyui_reachable(SETTINGS.comfyui_url)
HAS_LLM = resolve_llm_name(SETTINGS) != "mock"
OUT = REPO_DIR / "samples" / "integration_output" / "phase5"
STORY = (REPO_DIR / "samples" / "stories" / "action_rooftop_chase.txt").read_text(encoding="utf-8")
CHAPTER_2 = (REPO_DIR / "samples" / "stories" / "action_rooftop_chase_ch2.txt").read_text(encoding="utf-8")

needs_comfy = pytest.mark.skipif(not HAS_COMFY, reason="ComfyUI is not reachable")


@pytest.fixture(scope="module")
def chapter_one():
    """One real page (shared by the tests below): storyboard, Editor loop, Letterer, exports."""
    if not HAS_COMFY:
        pytest.skip("ComfyUI is not reachable")
    settings = real_settings()
    settings.output_dir = OUT
    settings.max_pages = 1
    settings.auto_approve = True
    if OUT.exists():
        shutil.rmtree(OUT)
    project = run_project(new_project(STORY, "p5-ch1", settings), settings=settings, job_dir=OUT / "p5-ch1")
    return settings, project


@needs_comfy
def test_editor_loop_on_real_images(chapter_one):
    _, project = chapter_one
    assert project.status == "done"
    assert all(r.attempts and r.status in ("accepted", "needs_review", "unreviewed") for r in project.panels)
    reviewed = [a for r in project.panels for a in r.attempts if a.review]
    assert reviewed, "the Editor reviewed nothing"
    if HAS_LLM:
        assert any(s.agent == "editor" and s.model != "mock" for s in project.trace)
    print(f"\nEditor: {len(reviewed)} reviews, redraws={project.budget.redraws}, "
          f"GPU {project.budget.gpu_seconds:.0f}s, cost ${project.usage.cost_usd:.3f}")


@needs_comfy
def test_storyboard_controlnet_on_real_images(chapter_one):
    settings, project = chapter_one
    caps = get_image_provider(settings).comfy.capabilities()
    if not caps.has_controlnet:
        pytest.skip("ControlNet model/nodes not installed")
    assert len(project.storyboards) == len(project.prompts)
    assert any(f.control for f in project.storyboards)
    assert any("controlnet" in a.workflow for r in project.panels for a in r.attempts)


@needs_comfy
def test_letterer_on_real_art(chapter_one):
    settings, project = chapter_one
    step = next(s for s in project.trace if s.agent == "letterer")
    assert step.output["layers"] > 0
    assert all(pl.faces for pl in project.lettering)
    assert (OUT / "p5-ch1" / project.outputs["rtl"]["cbz"]).exists() and project.outputs["rtl"]["webtoon"]


@needs_comfy
def test_inpainting_on_real_panel(chapter_one):
    settings, project = chapter_one
    result = next(r for r in project.panels if r.image)
    before = Image.open(OUT / "p5-ch1" / result.image).convert("L")
    mask = Image.new("L", before.size, 0)
    ImageDraw.Draw(mask).ellipse((before.width * 0.3, before.height * 0.1, before.width * 0.7, before.height * 0.4), fill=255)
    mask_path = OUT / "p5-ch1" / "panels" / "it_mask.png"
    mask.save(mask_path)
    image = get_image_provider(settings)
    ctx = Ctx(settings=settings, llm=get_llm_provider(settings), image=image, job_dir=OUT / "p5-ch1")
    done = inpaint_panel(project, ctx, result.page, result.panel, mask_path, "a surprised face, wide eyes", "auto")
    new = done.attempts[-1]
    after = Image.open(OUT / "p5-ch1" / new.image).convert("L").resize(before.size)
    outside = ImageChops.multiply(ImageChops.difference(before, after).point(lambda v: 255 if v > 40 else 0),
                                  mask.point(lambda v: 0 if v else 255))
    changed_outside = sum(outside.histogram()[255:]) / (before.width * before.height)
    assert new.source in ("inpaint", "redraw") and changed_outside < 0.02     # the rest stays (nearly) the same


@needs_comfy
def test_panel_revision_on_real_panel(chapter_one):
    settings, project = chapter_one
    result = next(r for r in project.panels if r.image)
    ctx = Ctx(settings=settings, llm=get_llm_provider(settings), image=get_image_provider(settings), job_dir=OUT / "p5-ch1")
    done = revise_panel(project, ctx, result.page, result.panel, "make the emotion stronger")
    assert done.attempts[-1].round > 1 and any(s.agent == "panel_revision" for s in project.trace)


@pytest.mark.skipif(not (HAS_COMFY or HAS_LLM), reason="no ComfyUI and no LLM key")
def test_end_to_end_chapter_two(chapter_one):
    settings, first = chapter_one
    second = run_project(new_project(CHAPTER_2, "p5-ch2", settings, project_id=first.project_id), settings=settings,
                         job_dir=OUT / "p5-ch2")
    assert second.status == "done" and second.chapter == 2 and second.story_so_far
    assert any(c.reused_from == first.project_id for c in second.characters)


@pytest.mark.skipif(not (HAS_COMFY and kohya_available(SETTINGS) and os.environ.get("RUN_LORA_TRAINING") == "1"),
                    reason="needs ComfyUI + kohya sd-scripts + RUN_LORA_TRAINING=1 (about 20 minutes)")
def test_lora_training_real(chapter_one):
    from app.agents.cast_store import CastStore
    from app.training.lora import train_character_lora
    settings, project = chapter_one
    character = project.character(project.main_character_names()[0])
    store = CastStore(settings.output_dir).root / project.project_id
    result = train_character_lora(project, character, OUT / "p5-ch1", store, settings, progress=lambda f, m: None)
    assert result["trainer"] == "kohya" and result["status"] == "ready"
    assert (store / "loras" / character.slug / f"{result['file']}").exists()
