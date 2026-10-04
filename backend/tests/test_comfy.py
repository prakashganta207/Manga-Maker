"""ComfyUI workflows + client + provider, tested offline with a fake ComfyUI server."""

import io
import json

import httpx
import pytest
from PIL import Image

from app.comfy.client import ComfyClient
from app.comfy.workflows import WorkflowError, build_workflow, inject, load_template, placeholders, required_nodes
from app.config import Settings
from app.providers.base import ImageRequest, ProviderError
from app.providers.comfyui_image import ComfyUIImageProvider
from app.tools import comfy_check

CORE = ["CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "KSampler", "VAEDecode",
        "SaveImage", "LoadImage"]
IPA = ["IPAdapterUnifiedLoader", "IPAdapterAdvanced", "IPAdapterModelLoader", "CLIPVisionLoader"]


def object_info(ipadapter=True, checkpoints=("animagine-xl-3.1.safetensors",)):
    info = {name: {"input": {"required": {}}} for name in CORE + (IPA if ipadapter else [])}
    info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"] = [list(checkpoints)]
    if ipadapter:
        info["IPAdapterModelLoader"]["input"]["required"]["ipadapter_file"] = [["ip-adapter-plus_sdxl_vit-h.safetensors"]]
        # newer ComfyUI "COMBO" format
        info["CLIPVisionLoader"]["input"]["required"]["clip_name"] = [
            "COMBO", {"options": ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]}]
    return info


def png_bytes(size=(64, 96)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


class FakeComfy:
    """Minimal fake of the ComfyUI HTTP API."""

    def __init__(self, ipadapter=True, fail_with=None, checkpoints=("animagine-xl-3.1.safetensors",)):
        self.info = object_info(ipadapter, checkpoints)
        self.fail_with = fail_with
        self.workflows, self.uploads, self.freed = [], [], 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"name": "RTX 4060", "vram_total": 8 * 1024**3,
                                                          "vram_free": 7 * 1024**3}]})
        if path == "/object_info":
            return httpx.Response(200, json=self.info)
        if path == "/upload/image":
            self.uploads.append(request)
            return httpx.Response(200, json={"name": f"ref{len(self.uploads)}.png", "subfolder": ""})
        if path == "/prompt":
            self.workflows.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "p1"})
        if path == "/history/p1":
            if self.fail_with:
                return httpx.Response(200, json={"p1": {"status": {"status_str": "error",
                                                                   "messages": [self.fail_with]}}})
            return httpx.Response(200, json={"p1": {"status": {"completed": True}, "outputs": {
                "9": {"images": [{"filename": "a.png", "type": "output"}]}}}})
        if path == "/view":
            return httpx.Response(200, content=png_bytes())
        if path == "/free":
            self.freed += 1
            return httpx.Response(200, json={})
        return httpx.Response(404)


def make_provider(fake, **settings):
    s = Settings(comfyui_url="http://comfy:8188", **settings)
    return ComfyUIImageProvider(s, client=httpx.Client(transport=httpx.MockTransport(fake)), poll_interval=0)


def ref_file(tmp_path, name="mira.png"):
    path = tmp_path / name
    path.write_bytes(png_bytes())
    return path


# --------------------------------------------------------------------------- templates
@pytest.mark.parametrize("name", ["txt2img", "ipadapter_1ref", "ipadapter_2ref"])
def test_templates_are_valid_graphs(name):
    wf = load_template(name)
    for node_id, node in wf.items():
        for value in node["inputs"].values():
            if isinstance(value, list):  # a link -> must point to an existing node
                assert value[0] in wf, f"{name}: node {node_id} links to missing {value[0]}"
    assert {"seed", "prompt", "negative_prompt", "width", "height", "checkpoint"} <= placeholders(wf)


def test_inject_keeps_types_and_substitutes_inside_strings():
    wf = inject({"a": "{{seed}}", "b": "prefix {{name}}!", "c": ["{{seed}}", 0], "d": "{{unknown}}"},
                {"seed": 7, "name": "x"})
    assert wf == {"a": 7, "b": "prefix x!", "c": [7, 0], "d": "{{unknown}}"}


def test_build_workflow_rejects_unfilled_placeholders():
    with pytest.raises(WorkflowError, match="unfilled"):
        build_workflow("txt2img", {"prompt": "x"})


def test_build_workflow_ipadapter_parameters():
    values = dict(checkpoint="c.safetensors", prompt="p", negative_prompt="n", seed=1, width=832, height=1216,
                  steps=28, cfg=6.0, sampler="euler", scheduler="normal", filename_prefix="t",
                  ipadapter_preset="PLUS (high strength)", ipadapter_weight=0.7, ipadapter_weight_2=0.45,
                  ipadapter_end_at=0.8, reference_image_1="a.png", reference_image_2="b.png")
    wf = build_workflow("ipadapter_2ref", values)
    assert wf["12"]["inputs"]["weight"] == 0.45 and wf["14"]["inputs"]["weight"] == 0.45
    assert wf["11"]["inputs"]["image"] == "a.png" and wf["13"]["inputs"]["image"] == "b.png"
    assert wf["3"]["inputs"]["model"] == ["14", 0]  # the sampler uses the IP-Adapter-patched model
    assert "_meta" not in wf["4"]
    assert {"IPAdapterUnifiedLoader", "IPAdapterAdvanced"} <= required_nodes(wf)


# --------------------------------------------------------------------------- discovery
def test_capabilities_from_object_info():
    client = ComfyClient("http://comfy", client=httpx.Client(transport=httpx.MockTransport(FakeComfy())))
    caps = client.capabilities()
    assert caps.has_ipadapter
    assert caps.checkpoints == ["animagine-xl-3.1.safetensors"]
    assert caps.clip_vision_models == ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]


def test_pick_checkpoint_prefers_configured_then_anime():
    fake = FakeComfy(checkpoints=("sd_xl_base_1.0.safetensors", "my_anime_xl.safetensors"))
    client = ComfyClient("http://comfy", client=httpx.Client(transport=httpx.MockTransport(fake)))
    assert client.pick_checkpoint("sd_xl_base_1.0.safetensors") == "sd_xl_base_1.0.safetensors"
    assert client.pick_checkpoint("animagine-xl-3.1.safetensors") == "my_anime_xl.safetensors"


# --------------------------------------------------------------------------- provider
def test_panel_with_one_reference_uses_ipadapter(tmp_path):
    fake = FakeComfy()
    provider = make_provider(fake)
    provider.generate(ImageRequest(prompt="p", width=832, height=1216, seed=5,
                                   reference_images=[ref_file(tmp_path)]))
    wf = fake.workflows[0]
    assert wf["12"]["class_type"] == "IPAdapterAdvanced"
    assert wf["12"]["inputs"]["weight"] == 0.7 and wf["11"]["inputs"]["image"] == "ref1.png"
    assert wf["5"]["inputs"]["width"] == 832 and wf["3"]["inputs"]["seed"] == 5
    assert wf["4"]["inputs"]["ckpt_name"] == "animagine-xl-3.1.safetensors"
    assert provider.last_info["workflow"] == "ipadapter_1ref"


def test_two_references_use_reduced_weights_and_upload_once(tmp_path):
    fake = FakeComfy()
    provider = make_provider(fake, ipadapter_weight=0.8)
    refs = [ref_file(tmp_path, "a.png"), ref_file(tmp_path, "b.png")]
    provider.generate(ImageRequest(prompt="p", reference_images=refs))
    provider.generate(ImageRequest(prompt="p", reference_images=refs))
    assert fake.workflows[0]["12"]["inputs"]["weight"] == pytest.approx(0.52)
    assert len(fake.uploads) == 2  # cached after the first upload


def test_falls_back_to_txt2img_without_ipadapter(tmp_path):
    fake = FakeComfy(ipadapter=False)
    provider = make_provider(fake)
    provider.generate(ImageRequest(prompt="p", reference_images=[ref_file(tmp_path)]))
    assert "IPAdapterAdvanced" not in required_nodes(fake.workflows[0])
    assert provider.warnings and "IP-Adapter" in provider.warnings[0]


def test_character_sheets_never_use_ipadapter(tmp_path):
    fake = FakeComfy()
    make_provider(fake).generate(ImageRequest(prompt="p", kind="turnaround", reference_images=[ref_file(tmp_path)]))
    assert "IPAdapterAdvanced" not in required_nodes(fake.workflows[0])


def test_out_of_memory_error_gives_hint():
    provider = make_provider(FakeComfy(fail_with="CUDA out of memory"))
    with pytest.raises(ProviderError, match="lowvram"):
        provider.generate(ImageRequest(prompt="p"))


def test_free_memory_calls_free_endpoint():
    fake = FakeComfy()
    make_provider(fake).free_memory()
    assert fake.freed == 1
    make_provider(fake, comfyui_free_vram=False).free_memory()
    assert fake.freed == 1


def test_comfyui_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError, match="Cannot reach ComfyUI"):
        make_provider(handler).generate(ImageRequest(prompt="x"))


def test_check_tool_reports_unreachable(monkeypatch, capsys):
    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:9")  # nothing listens on port 9
    assert comfy_check.main([]) == 2
    assert "NOT reachable" in capsys.readouterr().out
