"""IP-Adapter panel generation (via a fake ComfyUI) + consistency scoring."""

import os
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageDraw

from app.agents.pipeline import new_project, run_project
from app.agents.prompt_builder import expression_for
from app.config import BACKEND_DIR
from app.providers.comfyui_image import ComfyUIImageProvider
from app.vision.consistency import ClipScorer, Scorer, SimpleScorer, cosine, get_scorer
from tests.test_comfy import FakeComfy


def save(img, path):
    img.save(path)
    return path


def drawing(tmp_path, name, shape):
    img = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(img)
    if shape == "circle":
        draw.ellipse((20, 20, 108, 108), fill="black")
    else:
        draw.rectangle((0, 90, 128, 128), fill="black")
    return save(img, tmp_path / f"{name}.png")


# --------------------------------------------------------------------------- scorer
def test_cosine():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)


def test_scorer_takes_best_reference_and_caches_embeddings(tmp_path):
    calls = []

    def embed(img):
        calls.append(img.size)
        return [float(sum(img.convert("L").tobytes()) % 97), 1.0]

    scorer = Scorer(embed)
    panel = drawing(tmp_path, "panel", "circle")
    same = drawing(tmp_path, "same", "circle")
    other = drawing(tmp_path, "other", "floor")
    assert scorer.score(panel, [other, same]) == pytest.approx(1.0)   # best match wins
    scorer.score(panel, [same])
    assert len(calls) == 3                                             # cached per file
    assert scorer.score(panel, [tmp_path / "missing.png"]) is None


def test_simple_scorer_ranks_similar_higher(tmp_path):
    scorer = SimpleScorer()
    panel = drawing(tmp_path, "panel", "circle")
    assert scorer.score(panel, [drawing(tmp_path, "a", "circle")]) > scorer.score(panel, [drawing(tmp_path, "b", "floor")])


def test_get_scorer_modes():
    assert get_scorer("off", "x") is None
    assert get_scorer("simple", "x").method == "simple"


CLIP_CACHED = (BACKEND_DIR / ".cache" / "huggingface" / "hub" / "models--openai--clip-vit-base-patch32").exists()


@pytest.mark.skipif(not CLIP_CACHED or os.environ.get("SKIP_CLIP") == "1", reason="CLIP model not downloaded")
def test_real_clip_scores_same_character_higher(tmp_path):
    from app.providers.base import ImageRequest
    from app.providers.mock_image import MockImageProvider

    mock = MockImageProvider()
    render = lambda seed, shot, chars: mock.generate(ImageRequest(  # noqa: E731
        prompt="x", width=256, height=256, seed=seed, metadata={"shot": shot, "characters": chars}))
    panel = save(render(1, "medium", ["Mira"]), tmp_path / "p.png")
    same = save(render(2, "close-up", ["Mira"]), tmp_path / "s.png")
    scenery = save(render(3, "establishing", []), tmp_path / "e.png")
    scorer = ClipScorer()
    assert scorer.score(panel, [same]) > scorer.score(panel, [scenery])


# --------------------------------------------------------------------------- pipeline
def test_pipeline_scores_every_panel(story, settings, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "job", settings), settings=settings, job_dir=tmp_path)
    main = set(project.main_character_names())
    for result in project.panels:
        assert result.consistency_method == "simple"
        prompt = next(x for x in project.prompts if (x.page, x.panel) == (result.page, result.panel))
        expected = {n for n in prompt.characters if n in main}   # only characters with reference sheets
        assert set(result.consistency) == expected
        assert all(-1 <= v <= 1 for v in result.consistency.values())


def test_panels_use_ipadapter_with_emotion_matched_references(story, settings, tmp_path):
    """Full run against a fake ComfyUI server: sheets via txt2img, panels via IP-Adapter."""
    settings.auto_approve = True
    settings.ipadapter_weight = 0.65
    fake = FakeComfy()
    settings.comfyui_url = "http://comfy:8188"
    provider = ComfyUIImageProvider(settings, client=httpx.Client(transport=httpx.MockTransport(fake)), poll_interval=0)
    project = run_project(new_project(story, "job", settings), settings=settings, job_dir=tmp_path, image=provider)
    assert project.status == "done"

    sheets = [w for w in fake.workflows if w["5"]["inputs"]["width"] in (1216, 1536)]
    assert sheets and all("12" not in w for w in sheets)                       # character sheets: plain txt2img
    with_refs = [p for p in project.prompts if p.references]
    assert with_refs, "panels with main characters must carry reference images"
    for spec in with_refs:
        assert spec.ipadapter_weight == 0.65
        for label, ref in zip(spec.reference_kinds, spec.references):
            name, kind = label.split(": ")
            planned = next(pn for _, pn in project.page_plan.all_panels()
                           if (_.page_number, pn.panel_number) == (spec.page, spec.panel))
            wanted = expression_for(planned.emotion)
            assert kind in (wanted, "front")                                   # matching expression if any
            assert Path(tmp_path / ref).exists()
    ip_workflows = [w for w in fake.workflows if "12" in w and w["12"]["class_type"] == "IPAdapterAdvanced"]
    assert len(ip_workflows) == len(with_refs)
    two_ref = [w for w in ip_workflows if "14" in w]
    for w in two_ref:                                                          # 2 characters: reduced weight
        assert w["12"]["inputs"]["weight"] == pytest.approx(0.65 * 0.65, abs=1e-3)
    assert fake.freed >= 2                                                     # VRAM freed between stages
    assert {r.workflow for r in project.panels} <= {"txt2img", "ipadapter_1ref", "ipadapter_2ref"}
