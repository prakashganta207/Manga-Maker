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


def png_bytes(size=(64, 96)):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- Hosted stub
def test_hosted_provider_generic_contract():
    def handler(request):
        assert request.headers["authorization"] == "Bearer k"
        assert json.loads(request.content)["seed"] == 9
        return httpx.Response(200, json={"image_base64": base64.b64encode(png_bytes((20, 30))).decode()})

    provider = HostedImageProvider(Settings(hosted_image_api_url="http://h/gen", hosted_image_api_key="k"),
                                   client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.generate(ImageRequest(prompt="x", seed=9)).size == (20, 30)
