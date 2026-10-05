"""Phase 5 M9: storyboard roughs, control images, ControlNet injection, 8 GB fallback."""

import json

import httpx
import pytest
from PIL import Image, ImageDraw

from app.agents import storyboard as sb
from app.agents.pipeline import new_project, run_project
from app.comfy.workflows import add_controlnet, build_workflow, load_template, placeholders
from app.providers.base import ImageRequest
from app.providers.mock_image import MockImageProvider
from tests.test_comfy import FakeComfy, make_provider, png_bytes, ref_file

CN_NODES = ["ControlNetLoader", "SetUnionControlNetType", "ControlNetApplyAdvanced", "DWPreprocessor",
            "AnimeLineArtPreprocessor"]


def fake_with_controlnet(**kw) -> FakeComfy:
    fake = FakeComfy(**kw)
    for name in CN_NODES:
        fake.info[name] = {"input": {"required": {}}}
    fake.info["ControlNetLoader"]["input"]["required"]["control_net_name"] = [["controlnet-union-sdxl-1.0.safetensors"]]
    return fake


# --------------------------------------------------------------------------- workflow injection
@pytest.mark.parametrize("base", ["txt2img", "ipadapter_1ref", "ipadapter_2ref"])
def test_add_controlnet_rewires_the_sampler(base):
    values = {k: 1 for k in placeholders(load_template(base))}
    wf = build_workflow(base, values)
    out = add_controlnet(wf, model="cn.safetensors", image="pose.png", control_type="openpose", strength=0.5, end=0.6)
    apply = out["63"]["inputs"]
    assert apply["positive"] == ["6", 0] and apply["negative"] == ["7", 0]     # the prompts go in ...
    assert out["3"]["inputs"]["positive"] == ["63", 0] and out["3"]["inputs"]["negative"] == ["63", 1]  # ... guided out
    assert out["61"]["inputs"]["type"] == "openpose" and apply["strength"] == 0.5 and apply["end_percent"] == 0.6
    assert out["3"]["inputs"]["model"] == wf["3"]["inputs"]["model"]            # IP-Adapter chain untouched
    assert "63" not in wf                                                        # the input is not modified


def test_lineart_uses_the_union_lineart_mode():
    wf = build_workflow("txt2img", {k: 1 for k in placeholders(load_template("txt2img"))})
    out = add_controlnet(wf, model="m", image="i", control_type="lineart", strength=1, end=1)
    assert out["61"]["inputs"]["type"] == "canny/lineart/anime_lineart/mlsd"


def test_provider_adds_controlnet_when_available(tmp_path):
    fake = fake_with_controlnet()
    provider = make_provider(fake, controlnet_strength=0.5)
    request = ImageRequest(prompt="p", kind="panel", reference_images=[ref_file(tmp_path)],
                           control_image=ref_file(tmp_path, "pose.png"), control_strength=0.45, control_end=0.5)
    name, wf = provider.build(request)
    assert name == "ipadapter_1ref+controlnet"
    assert wf["63"]["inputs"]["strength"] == 0.45 and wf["60"]["inputs"]["control_net_name"].startswith("controlnet-union")
    assert provider.supports_controlnet()
    assert provider.comfy.capabilities().summary()["controlnet_ready"]


def test_provider_without_controlnet_warns_and_draws_plainly(tmp_path):
    provider = make_provider(FakeComfy())
    name, wf = provider.build(ImageRequest(prompt="p", kind="panel", control_image=ref_file(tmp_path)))
    assert name == "txt2img" and "63" not in wf
    assert any("ControlNet" in w for w in provider.warnings) and not provider.supports_controlnet()


def test_storyboard_requests_use_fewer_steps(tmp_path):
    provider = make_provider(FakeComfy(), comfyui_steps=28, storyboard_steps=16)
    _, wf = provider.build(ImageRequest(prompt="p", kind="storyboard", width=576, height=832))
    assert wf["3"]["inputs"]["steps"] == 16


def test_preprocess_workflows(tmp_path):
    fake = fake_with_controlnet()
    provider = make_provider(fake)
    image = provider.preprocess(ref_file(tmp_path, "rough.png"), "openpose")
    assert image is not None and fake.workflows[-1]["2"]["class_type"] == "DWPreprocessor"
    provider.preprocess(ref_file(tmp_path, "rough.png"), "lineart")
    assert fake.workflows[-1]["2"]["class_type"] == "AnimeLineArtPreprocessor"
    assert make_provider(FakeComfy()).preprocess(ref_file(tmp_path, "r.png"), "openpose") is None


def test_out_of_vram_retries_without_controlnet(tmp_path):
    """8 GB rule: if ControlNet + IP-Adapter runs out of memory, retry without ControlNet."""
    fake = fake_with_controlnet()
    calls = {"n": 0}
    original = fake.__call__

    def flaky(request):
        if request.url.path == "/history/p1":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, json={"p1": {"status": {"status_str": "error",
                                                                   "messages": ["CUDA out of memory"]}}})
        return original(request)

    from app.config import Settings
    from app.providers.comfyui_image import ComfyUIImageProvider
    provider = ComfyUIImageProvider(Settings(comfyui_url="http://comfy:8188"),
                                    client=httpx.Client(transport=httpx.MockTransport(flaky)), poll_interval=0)
    provider.generate(ImageRequest(prompt="p", kind="panel", control_image=ref_file(tmp_path, "pose.png")))
    assert "63" in fake.workflows[0] and "63" not in fake.workflows[1]
    assert provider.last_info["fallback"].startswith("out of VRAM") and fake.freed >= 1


# --------------------------------------------------------------------------- storyboard stage
def test_control_coverage():
    black = Image.new("RGB", (100, 100), "black")
    assert sb.control_coverage(black) == 0
    ImageDraw.Draw(black).line((0, 50, 100, 50), fill="white", width=4)
    assert sb.control_coverage(black) == pytest.approx(0.04, abs=0.01)


def test_pipeline_draws_storyboards_and_uses_them(settings, story, tmp_path):
    settings.auto_approve = True
    seen = []

    class Spy(MockImageProvider):
        def generate(self, request):
            seen.append(request)
            return super().generate(request)

    project = run_project(new_project(story, "sb", settings), settings=settings, job_dir=tmp_path, image=Spy())
    assert len(project.storyboards) == len(project.prompts)
    for frame in project.storyboards:
        assert (tmp_path / frame.rough).exists()
        if frame.control:
            assert (tmp_path / frame.control).exists()
    roughs = [r for r in seen if r.kind == "storyboard"]
    assert len(roughs) == len(project.prompts) and max(r.width for r in roughs) <= 1024
    panels = [r for r in seen if r.kind == "panel"]
    assert any(r.control_image for r in panels)
    controlled = [a for r in project.panels for a in r.attempts if a.extra.get("control")]
    assert controlled and controlled[0].extra["control_strength"] == settings.controlnet_strength
    step = next(s for s in project.trace if s.agent == "storyboard")
    assert step.status == "ok" and step.output["frames"] == len(project.prompts)
    scenery = [f for f in project.storyboards
               if not next(pn for _, pn in project.page_plan.all_panels()
                           if (_.page_number, pn.panel_number) == (f.page, f.panel)).characters]
    assert all(f.control_type == "lineart" for f in scenery if f.control)


def test_pose_falls_back_to_lineart(settings, story, tmp_path, monkeypatch):
    settings.auto_approve = True

    class NoPose(MockImageProvider):
        def preprocess(self, image, mode):
            return Image.new("RGB", (64, 64), "black") if mode == "openpose" else super().preprocess(image, mode)

    project = run_project(new_project(story, "fb", settings), settings=settings, job_dir=tmp_path, image=NoPose())
    with_people = [f for f in project.storyboards if f.control]
    assert with_people and all(f.control_type == "lineart" for f in with_people)
    assert any("no pose found" in f.note for f in project.storyboards)


def test_storyboard_off(settings, story, tmp_path):
    settings.auto_approve = True
    settings.storyboard = "off"
    project = run_project(new_project(story, "off", settings), settings=settings, job_dir=tmp_path)
    assert project.storyboards == [] and project.status == "done"
    assert next(s for s in project.trace if s.agent == "storyboard").status == "skipped"
    assert not any(a.extra.get("control") for r in project.panels for a in r.attempts)
