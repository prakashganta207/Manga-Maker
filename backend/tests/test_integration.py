"""End-to-end integration test with REAL providers.

Skipped automatically unless ComfyUI answers at COMFYUI_URL or an LLM key is configured
(ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_BASE_URL + OPENAI_API_KEY in .env).
Whatever is available is used for real; the rest stays mock. Output is written to
samples/integration_output/<story>/ so you can look at it.

    cd backend && .venv/Scripts/python -m pytest tests/test_integration.py -s
"""

import shutil

import pytest

from app.agents.pipeline import new_project, run_project
from app.config import REPO_DIR, Settings
from app.providers.factory import comfyui_reachable, resolve_llm_name
from tests.conftest import ORIGINAL_PROVIDERS


def real_settings() -> Settings:
    settings = Settings.from_env()
    settings.llm_provider = ORIGINAL_PROVIDERS["LLM_PROVIDER"]
    settings.image_provider = ORIGINAL_PROVIDERS["IMAGE_PROVIDER"]
    return settings


SETTINGS = real_settings()
HAS_LLM = resolve_llm_name(SETTINGS) != "mock"
HAS_COMFY = SETTINGS.image_provider in ("auto", "comfyui") and comfyui_reachable(SETTINGS.comfyui_url)


@pytest.mark.skipif(not (HAS_LLM or HAS_COMFY), reason="no ComfyUI and no LLM key available")
def test_sample_story_end_to_end():
    story_file = REPO_DIR / "samples" / "stories" / "action_rooftop_chase.txt"
    out = REPO_DIR / "samples" / "integration_output" / story_file.stem
    if out.exists():
        shutil.rmtree(out)
    settings = SETTINGS
    settings.auto_approve = True
    settings.max_pages = 1  # keep the real run (and its cost) small
    if not HAS_COMFY:
        settings.image_provider = "mock"
    if not HAS_LLM:
        settings.llm_provider = "mock"

    events = []
    project = run_project(new_project(story_file.read_text(encoding="utf-8"), "integration", settings),
                          settings=settings, job_dir=out, progress=lambda s, f, m: events.append(m))
    assert project.status == "done", project.error
    assert project.providers["llm"] != "mock" or project.providers["image"] != "mock"
    assert (out / project.outputs["rtl"]["pdf"]).exists()
    assert all(r.consistency_method for r in project.panels)
    print(f"\nproviders={project.providers} usage={project.usage.model_dump()} timings={project.timings}")
