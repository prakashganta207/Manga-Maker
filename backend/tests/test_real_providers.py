"""Real providers, tested offline with fake clients (no API keys, no network)."""

import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app.config import Settings
from app.models import MangaScript
from app.pipeline.script import generate_script
from app.providers.anthropic_llm import AnthropicLLMProvider, to_structured_output_schema
from app.providers.base import ImageRequest, ProviderError
from app.providers.comfyui_image import ComfyUIImageProvider, default_workflow, fill_placeholders
from app.providers.hosted_image import HostedImageProvider
from app.providers.mock_llm import MockLLMProvider


# --------------------------------------------------------------------------- Anthropic
def test_schema_conversion_strips_unsupported_and_closes_objects():
    schema = to_structured_output_schema(MangaScript.model_json_schema())
    text = json.dumps(schema)
    for key in ("minLength", "maxLength", "minItems", "maxItems", "minimum"):
        assert f'"{key}"' not in text
    assert schema["additionalProperties"] is False
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def fake_client(*responses):
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, stop_details=None,
                           content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=text)])


def test_anthropic_provider_request_and_parse(story):
    script = MockLLMProvider().build_script(story)
    client, messages = fake_client(text_response(json.dumps(script)))
    provider = AnthropicLLMProvider(Settings(anthropic_api_key="x"), client=client)
    result, _ = generate_script(story, provider)
    assert result.title == script["title"]
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "<story>" in call["messages"][0]["content"]
    assert call["fallbacks"] == "default"
    assert "temperature" not in call and "thinking" not in call


def test_anthropic_invalid_answer_triggers_repair(story):
    script = MockLLMProvider().build_script(story)
    broken = dict(script, pages=[])
    client, messages = fake_client(text_response(json.dumps(broken)), text_response(json.dumps(script)))
    provider = AnthropicLLMProvider(Settings(anthropic_api_key="x"), client=client)
    generate_script(story, provider)
    assert len(messages.calls) == 2
    assert "rejected by the validator" in messages.calls[1]["messages"][0]["content"]


def test_anthropic_refusal_becomes_provider_error():
    refusal = SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[])
    client, _ = fake_client(refusal)
    provider = AnthropicLLMProvider(Settings(anthropic_api_key="x"), client=client)
    with pytest.raises(ProviderError, match="declined"):
        provider.generate_json(system="s", user="u", schema={}, task="manga_script", context={})


def test_anthropic_requires_key():
    with pytest.raises(ProviderError):
        AnthropicLLMProvider(Settings(anthropic_api_key=""))


# --------------------------------------------------------------------------- ComfyUI
def png_bytes(size=(64, 96)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def test_fill_placeholders_keeps_types():
    wf = fill_placeholders(default_workflow("m.safetensors", 20, 6.0),
                           {"prompt": "a cat", "negative_prompt": "color", "seed": 5, "width": 512, "height": 768})
    assert wf["5"]["inputs"]["width"] == 512 and wf["3"]["inputs"]["seed"] == 5
    assert wf["6"]["inputs"]["text"] == "a cat"


def test_comfyui_round_trip():
    seen = {"polls": 0}

    def handler(request: httpx.Request):
        if request.url.path == "/prompt":
            seen["workflow"] = json.loads(request.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "abc"})
        if request.url.path == "/history/abc":
            seen["polls"] += 1
            if seen["polls"] < 2:
                return httpx.Response(200, json={})  # still running
            return httpx.Response(200, json={"abc": {
                "status": {"completed": True, "status_str": "success"},
                "outputs": {"9": {"images": [{"filename": "manga_1.png", "subfolder": "", "type": "output"}]}}}})
        if request.url.path == "/view":
            assert request.url.params["filename"] == "manga_1.png"
            return httpx.Response(200, content=png_bytes())
        return httpx.Response(404)

    settings = Settings(comfyui_url="http://comfy:8188", comfyui_checkpoint="anime.safetensors")
    provider = ComfyUIImageProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                    poll_interval=0)
    image = provider.generate(ImageRequest(prompt="ink drawing", negative_prompt="color",
                                           width=512, height=768, seed=42))
    assert image.size == (64, 96)
    wf = seen["workflow"]
    assert wf["4"]["inputs"]["ckpt_name"] == "anime.safetensors"
    assert wf["3"]["inputs"]["seed"] == 42 and wf["5"]["inputs"]["height"] == 768
    assert wf["6"]["inputs"]["text"] == "ink drawing"


def test_comfyui_reports_workflow_errors():
    def handler(request):
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p"})
        return httpx.Response(200, json={"p": {"status": {"status_str": "error", "messages": ["bad ckpt"]},
                                               "outputs": {}}})

    provider = ComfyUIImageProvider(Settings(comfyui_url="http://c"),
                                    client=httpx.Client(transport=httpx.MockTransport(handler)), poll_interval=0)
    with pytest.raises(ProviderError, match="bad ckpt"):
        provider.generate(ImageRequest(prompt="x"))


def test_comfyui_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    provider = ComfyUIImageProvider(Settings(comfyui_url="http://c"),
                                    client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError, match="Cannot reach ComfyUI"):
        provider.generate(ImageRequest(prompt="x"))


def test_comfyui_custom_workflow_uploads_reference(tmp_path):
    workflow = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{reference_image}}"}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}}}
    wf_file = tmp_path / "wf.json"
    wf_file.write_text(json.dumps(workflow))
    ref = tmp_path / "mira.png"
    ref.write_bytes(png_bytes())
    seen = {}

    def handler(request):
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "mira.png", "subfolder": ""})
        if request.url.path == "/prompt":
            seen["workflow"] = json.loads(request.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "p"})
        if request.url.path == "/history/p":
            return httpx.Response(200, json={"p": {"status": {"completed": True},
                                                   "outputs": {"9": {"images": [{"filename": "a.png"}]}}}})
        return httpx.Response(200, content=png_bytes())

    settings = Settings(comfyui_url="http://c", comfyui_workflow=str(wf_file))
    provider = ComfyUIImageProvider(settings, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                    poll_interval=0)
    provider.generate(ImageRequest(prompt="hello", reference_images=[ref]))
    assert seen["workflow"]["1"]["inputs"]["image"] == "mira.png"
    assert seen["workflow"]["2"]["inputs"]["text"] == "hello"


# --------------------------------------------------------------------------- Hosted stub
def test_hosted_provider_generic_contract():
    def handler(request):
        assert request.headers["authorization"] == "Bearer k"
        assert json.loads(request.content)["seed"] == 9
        return httpx.Response(200, json={"image_base64": base64.b64encode(png_bytes((20, 30))).decode()})

    provider = HostedImageProvider(Settings(hosted_image_api_url="http://h/gen", hosted_image_api_key="k"),
                                   client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.generate(ImageRequest(prompt="x", seed=9)).size == (20, 30)
