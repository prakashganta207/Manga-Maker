"""Phase 4 M6: inpainting — masks, workflow parameter injection, region character, endpoint."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from app.agents import inpaint as inpaint_module
from app.agents.inpaint import inpaint_prompt, region_character
from app.agents.pipeline import new_project, run_project
from app.agents.schemas import PlannedPanel
from app.comfy.workflows import build_workflow, load_template, placeholders
from app.main import create_app
from app.pipeline.masks import Stroke, bbox, coverage, rasterize, visible_region
from app.providers.base import ImageRequest
from app.vision.faces import Face
from tests.test_comfy import FakeComfy, make_provider, ref_file


# --------------------------------------------------------------------------- masks
def test_visible_region_undoes_cover_fit():
    # A tall 800x1200 image in a wide 600x300 slot: full width visible, a centred band of height 400.
    assert visible_region((800, 1200), (600, 300)) == (0.0, 400.0, 800.0, 400.0)
    assert visible_region((800, 800), (400, 400)) == (0.0, 0.0, 800.0, 800.0)


def test_rasterize_maps_slot_fractions_to_image_pixels():
    mask = rasterize([Stroke(points=[(0.5, 0.5)], size=0.1)], (800, 1200), (600, 300))
    box = bbox(mask)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    assert abs(cx - 400) <= 2 and abs(cy - 600) <= 2          # slot centre -> image centre
    assert 70 <= box[2] - box[0] <= 90                         # 10% of the 800 px visible width


def test_erase_strokes_remove_paint_and_coverage():
    paint = Stroke(points=[(0.1, 0.5), (0.9, 0.5)], size=0.2)
    erase = Stroke(points=[(0.5, 0.5)], size=0.3, erase=True)
    full = rasterize([paint], (400, 400), (400, 400))
    holed = rasterize([paint, erase], (400, 400), (400, 400))
    assert coverage(holed) < coverage(full)
    assert holed.getpixel((200, 200)) == 0 and full.getpixel((200, 200)) == 255
    assert coverage(rasterize([], (100, 100), (100, 100))) == 0


# --------------------------------------------------------------------------- workflow injection
def test_inpaint_templates_have_the_expected_placeholders():
    plain = placeholders(load_template("inpaint"))
    assert {"init_image", "mask_image", "denoise", "mask_grow", "mask_feather", "prompt", "seed"} <= plain
    assert "reference_image_1" in placeholders(load_template("inpaint_ipadapter"))


@pytest.mark.parametrize("with_ref, workflow", [(False, "inpaint"), (True, "inpaint_ipadapter")])
def test_comfy_provider_injects_inpaint_parameters(tmp_path, with_ref, workflow):
    fake = FakeComfy()
    provider = make_provider(fake, inpaint_grow=20, inpaint_feather=6)
    init, mask = ref_file(tmp_path, "panel.png"), ref_file(tmp_path, "mask.png")
    request = ImageRequest(prompt="a red scarf", negative_prompt="color", width=832, height=1216, seed=9,
                           kind="inpaint", init_image=init, mask_image=mask, denoise=0.75,
                           reference_images=[ref_file(tmp_path, "aya.png")] if with_ref else [])
    name, wf = provider.build(request)
    assert name == workflow and not placeholders(wf)
    assert wf["3"]["inputs"]["denoise"] == 0.75 and wf["3"]["inputs"]["seed"] == 9
    assert wf["23"]["inputs"]["expand"] == 20 and wf["27"]["inputs"]["left"] == 6
    assert wf["25"]["class_type"] == "SetLatentNoiseMask" and wf["26"]["inputs"]["mask"] == ["27", 0]
    assert wf["3"]["inputs"]["model"] == (["12", 0] if with_ref else ["4", 0])
    assert len(fake.uploads) == (3 if with_ref else 2)          # panel + mask (+ reference)
    provider.generate(request)                                  # runs against the fake server


def test_inpaint_without_mask_is_an_error(tmp_path):
    from app.providers.base import ProviderError
    provider = make_provider(FakeComfy())
    with pytest.raises(ProviderError):
        provider.build(ImageRequest(prompt="x", kind="inpaint"))


# --------------------------------------------------------------------------- region character + prompt
def test_region_character_uses_face_under_the_mask(monkeypatch, tmp_path):
    planned = PlannedPanel(panel_number=1, beat=1, purpose="p", size="medium", characters=["Aya", "Ken"],
                           action="a", setting="s", emotion="calm")
    monkeypatch.setattr(inpaint_module, "detect_faces", lambda img: [Face(600, 100, 100, 100), Face(100, 100, 100, 100)])
    mask = Image.new("L", (800, 600), 0)
    mask.paste(255, (620, 120, 680, 180))
    assert region_character(None, planned, tmp_path / "x.png", mask) == "Ken"   # right-hand face = 2nd character
    mask = Image.new("L", (800, 600), 0)
    mask.paste(255, (300, 400, 400, 500))
    assert region_character(None, planned, tmp_path / "x.png", mask) is None    # no face under the mask


def test_inpaint_endpoint_changes_only_the_masked_region(settings, story):
    settings.auto_approve = True
    run_project(new_project(story, "ip", settings), settings=settings, job_dir=settings.output_dir / "ip")
    with TestClient(create_app(settings)) as client:
        project = client.get("/api/jobs/ip/project").json()
        target = next(r for r in project["panels"] if r["page"] == 1)
        page, panel = target["page"], target["panel"]
        before = Image.open(settings.output_dir / "ip" / target["image"]).convert("L")
        body = {"strokes": [{"points": [0.2, 0.2, 0.4, 0.3], "size": 0.08}], "prompt": "a paper lantern",
                "character": ""}
        assert client.post(f"/api/jobs/ip/panels/{page}/{panel}/inpaint",
                           json={**body, "strokes": [{"points": [0.5, 0.5], "size": 0.001}]}).status_code == 422
        response = client.post(f"/api/jobs/ip/panels/{page}/{panel}/inpaint", json=body)
        assert response.status_code == 202, response.text
        for _ in range(100):
            job = client.get("/api/jobs/ip").json()
            if not job["busy"]:
                break
            time.sleep(0.1)
        assert job["error"] is None
        after_project = client.get("/api/jobs/ip/project").json()
        result = next(r for r in after_project["panels"] if (r["page"], r["panel"]) == (page, panel))
        last_round = max(a["round"] for a in result["attempts"])
        round_attempts = [a for a in result["attempts"] if a["round"] == last_round]
        new = round_attempts[0]
        assert new["source"] == "inpaint" and new["extra"]["region"] == "a paper lantern"
        assert "a paper lantern" in new["prompt"] and new["extra"]["mask"].endswith(".png")
        mask = Image.open(settings.output_dir / "ip" / new["extra"]["mask"]).convert("L")
        for attempt in round_attempts:              # Editor redraws repaint the same region of the same base
            assert attempt["extra"]["base"] == target["image"]
            after = Image.open(settings.output_dir / "ip" / attempt["image"]).convert("L")
            changed = ImageChops.difference(before, after).point(lambda v: 255 if v > 8 else 0)
            outside = ImageChops.multiply(changed, mask.point(lambda v: 0 if v > 0 else 255))
            assert bbox(changed) is not None            # something changed ...
            assert outside.getbbox() is None            # ... but nothing outside the mask
        assert client.post(f"/api/jobs/ip/panels/{page}/{panel}/inpaint",
                           json={**body, "character": "Nobody"}).status_code == 422


def test_inpaint_prompt_includes_character_tags(settings, story, tmp_path):
    settings.auto_approve = True
    project = run_project(new_project(story, "pp", settings), settings=settings, job_dir=tmp_path)
    name = project.characters[0].name
    prompt = inpaint_prompt(project, "her face, determined", name)
    assert project.characters[0].tag_prompt() in prompt and "her face, determined" in prompt
    assert "(" not in inpaint_prompt(project, "a lamp", None).split("manga, comic panel")[1].split("ink")[0]
