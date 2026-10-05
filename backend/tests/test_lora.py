"""Phase 5 M10: character LoRA training (mock trainer), dataset, kohya args, LoRA in workflows."""

import time

import pytest
from fastapi.testclient import TestClient

from app.agents.pipeline import new_project, panel_loras, run_project
from app.agents.prompt_builder import build_prompt
from app.comfy.workflows import add_loras, build_workflow, load_template, placeholders
from app.main import create_app
from app.providers.base import ImageRequest
from app.training import lora as lora_mod
from app.training.lora import build_dataset, collect_samples, parse_progress, training_args, trigger_word
from tests.test_comfy import FakeComfy, make_provider


@pytest.fixture
def done(settings, story, tmp_path):
    settings.auto_approve = True
    settings.trainer = "mock"
    project = run_project(new_project(story, "lr", settings), settings=settings, job_dir=tmp_path)
    return project, tmp_path


def test_dataset_and_captions(done, tmp_path_factory):
    project, job_dir = done
    character = project.characters[0]
    samples = collect_samples(project, character, job_dir)
    assert len(samples) >= 8                                    # 3 views + 5 expressions (+ solo panels)
    first = samples[0].caption
    assert first.startswith(trigger_word(character) + ", ") and character.tag_prompt() in first
    out = tmp_path_factory.mktemp("lora")
    dataset = build_dataset(samples, out, character, repeats=10, resolution=768)
    folder = dataset / f"10_{trigger_word(character)}"
    assert folder.is_dir() and len(list(folder.glob("*.png"))) == len(samples)
    assert len(list(folder.glob("*.txt"))) == len(samples)


def test_kohya_args_are_8gb_friendly(settings, tmp_path):
    args = training_args(settings, tmp_path / "ds", tmp_path / "out", "aya", tmp_path / "model.safetensors")
    for flag in ("--fp8_base", "--gradient_checkpointing", "--cache_latents", "--cache_text_encoder_outputs",
                 "--network_train_unet_only", "--train_batch_size=1", "--optimizer_type=Adafactor", "--sdpa",
                 "--resolution=768,768", "--network_dim=16"):
        assert flag in args
    assert args[0] == "sdxl_train_network.py"


@pytest.mark.parametrize("line, expected", [
    ("steps:  12%|##        | 75/600 [01:52<13:07,  1.50s/it, avr_loss=0.112]", (75, 600)),
    ("caching latents: 100%|##########| 8/8 [00:03<00:00,  2.4it/s]", None),   # not training steps
    ("epoch 1/8", None),
    ("loading model", None),
])
def test_parse_progress(line, expected):
    assert parse_progress(line) == expected


def test_add_loras_rewires_model_and_clip_but_not_vae():
    wf = build_workflow("ipadapter_1ref", {k: 1 for k in placeholders(load_template("ipadapter_1ref"))})
    out = add_loras(wf, [("aya.safetensors", 0.8), ("ken.safetensors", 0.6)])
    assert out["70"]["inputs"]["model"] == ["4", 0] and out["71"]["inputs"]["model"] == ["70", 0]
    assert out["10"]["inputs"]["model"] == ["71", 0]             # IP-Adapter loads the LoRA-patched model
    assert out["6"]["inputs"]["clip"] == ["71", 1]               # prompts use the LoRA-patched CLIP
    assert out["8"]["inputs"]["vae"] == ["4", 2]                 # the VAE comes straight from the checkpoint
    assert add_loras(wf, []) is wf


def test_provider_uses_only_installed_loras():
    fake = FakeComfy()
    fake.info["LoraLoader"] = {"input": {"required": {"lora_name": [["aya.safetensors"]]}}}
    provider = make_provider(fake)
    name, wf = provider.build(ImageRequest(prompt="p", kind="panel", loras=[("aya.safetensors", 0.8)]))
    assert name == "txt2img+lora" and wf["70"]["inputs"]["lora_name"] == "aya.safetensors"
    name, wf = provider.build(ImageRequest(prompt="p", kind="panel", loras=[("missing.safetensors", 0.8)]))
    assert "70" not in wf and any("LoRA" in w for w in provider.warnings)


def test_trained_lora_is_used_in_prompts(done, settings):
    project, _ = done
    character = project.characters[0]
    character.lora.status, character.lora.trainer = "ready", "kohya"
    character.lora.file, character.lora.trigger = "aya_lora.safetensors", "aya_chr"
    panel = next(pn for _, pn in project.page_plan.all_panels() if pn.characters == [character.name])
    directed = project.director.pages[0].panels[0]
    characters = {c.name.lower(): c for c in project.characters}
    assert "(aya_chr, " in build_prompt(panel, directed, characters)
    assert panel_loras(panel, characters, settings) == [("aya_lora.safetensors", settings.lora_strength)]
    character.lora.trainer = "mock"                              # mock LoRAs are demos, never used
    assert panel_loras(panel, characters, settings) == []


def test_train_endpoint_with_mock_trainer(settings, story):
    settings.auto_approve = True
    settings.trainer = "mock"
    run_project(new_project(story, "tr", settings), settings=settings, job_dir=settings.output_dir / "tr")
    with TestClient(create_app(settings)) as client:
        name = client.get("/api/jobs/tr/project").json()["characters"][0]["name"]
        assert client.get("/api/training/info").json()["trainer"] == "mock"
        started = client.post(f"/api/jobs/tr/characters/{name}/lora/train")
        assert started.status_code == 202, started.text
        tid = started.json()["id"]
        assert client.post(f"/api/jobs/tr/characters/{name}/lora/train").status_code == 409   # one at a time
        for _ in range(600):          # mock training ~1.5 s + 4 evaluation drawings
            state = client.get(f"/api/trainings/{tid}").json()
            if state["status"] in ("done", "failed"):
                break
            time.sleep(0.1)
        assert state["status"] == "done", state
        assert state["progress"] == 1.0 and any("mock" in line for line in state["log_tail"])
        lora = next(c for c in client.get("/api/jobs/tr/project").json()["characters"] if c["name"] == name)["lora"]
        assert lora["status"] == "ready" and lora["trainer"] == "mock" and lora["dataset_size"] >= 8
        assert lora["before"] is not None and lora["after"] is not None
        assert len(lora["eval_images"]["before"]) == 2
        assert client.get("/api/jobs/tr/trainings").json()[0]["id"] == tid
        cast = client.get("/api/projects").json()[0]
        assert cast["project_id"] == "tr"


def test_train_requires_approved_character(settings, story):
    settings.auto_approve = False
    run_project(new_project(story, "na", settings), settings=settings, job_dir=settings.output_dir / "na")
    with TestClient(create_app(settings)) as client:
        name = client.get("/api/jobs/na/project").json()["characters"][0]["name"]
        assert client.post(f"/api/jobs/na/characters/{name}/lora/train").status_code == 409


def test_import_lora(settings, story, tmp_path, monkeypatch):
    settings.auto_approve = True
    models = tmp_path / "models"
    (models / "loras").mkdir(parents=True)
    settings.comfyui_models_dir = str(models)
    run_project(new_project(story, "im", settings), settings=settings, job_dir=settings.output_dir / "im")
    with TestClient(create_app(settings)) as client:
        name = client.get("/api/jobs/im/project").json()["characters"][0]["name"]
        bad = client.post(f"/api/jobs/im/characters/{name}/lora/import", files={"file": ("x.txt", b"no")})
        assert bad.status_code == 422
        ok = client.post(f"/api/jobs/im/characters/{name}/lora/import",
                         files={"file": ("aya cloud.safetensors", b"\x08" + b"\x00" * 7 + b"{}")},
                         data={"trigger": "ayachr"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["installed_in_comfyui"] and (models / "loras" / "aya_cloud.safetensors").exists()
        lora = ok.json()["lora"]
        assert lora["status"] == "ready" and lora["trainer"] == "imported" and lora["trigger"] == "ayachr"


def test_resolve_trainer(settings, tmp_path):
    settings.trainer = "auto"
    settings.sd_scripts_dir = str(tmp_path / "nothing")
    assert lora_mod.resolve_trainer(settings) == "mock"
    settings.trainer = "kohya"
    assert lora_mod.resolve_trainer(settings) == "kohya"
