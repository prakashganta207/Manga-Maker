"""Schemas, the structured-output agent runner (retries), cost counting, LLM providers."""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.agents.cost import cost_usd
from app.agents.runner import AgentFailed, run_agent
from app.agents.safety import apply, rename_map
from app.agents.schemas import BeatSheet, DirectedPanel, PlannedPanel, VisualTags
from app.config import Settings
from app.providers.base import LLMProvider, LLMResponse, ProviderError, TokenUsage
from app.providers.gemini_llm import GeminiLLMProvider
from app.providers.openai_compat_llm import OpenAICompatibleLLMProvider
from app.providers.schema_utils import inline_refs


def beat_sheet_data(**overrides):
    data = {
        "title": "Rooftop", "logline": "Two friends see a strange light.", "emotional_arc": "calm -> awe",
        "beats": [{"id": 1, "summary": "Mira climbs to the roof.", "emotion": "calm", "intensity": 1, "kind": "setup"},
                  {"id": 2, "summary": "A glow rises from the river.", "emotion": "awe", "intensity": 5, "kind": "climax"}],
        "climax_beat": 2,
        "characters": [{"name": "Mira", "role": "protagonist", "importance": "main"}],
    }
    data.update(overrides)
    return data


class ScriptedLLM(LLMProvider):
    """Returns the given answers in order; records prompts."""

    name = "scripted"
    model = "claude-opus-5-5"

    def __init__(self, *answers, usage=TokenUsage(1000, 500)):
        self.answers = list(answers)
        self.prompts = []
        self.usage = usage

    def generate_json(self, *, system, user, schema, task, context):
        self.prompts.append(user)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(answer, self.usage, self.model)


def run(llm, **kwargs):
    return run_agent(agent="writer", label="Beat sheet", llm=llm, system="sys", user="Write beats.",
                     output_model=BeatSheet, task="beat_sheet", context={}, **kwargs)


# --------------------------------------------------------------------------- schemas
def test_beat_sheet_climax_must_exist():
    with pytest.raises(ValidationError, match="climax_beat"):
        BeatSheet.model_validate(beat_sheet_data(climax_beat=9))


def test_beat_sheet_duplicate_ids_rejected():
    data = beat_sheet_data()
    data["beats"][1]["id"] = 1
    with pytest.raises(ValidationError, match="unique"):
        BeatSheet.model_validate(data)


def test_shot_and_angle_spelling_normalised():
    panel = DirectedPanel(panel_number=1, shot="Extreme Close Up", angle="birds-eye", composition="x")
    assert panel.shot == "extreme close-up" and panel.angle == "bird's eye"
    assert DirectedPanel(panel_number=1, shot="OTS", angle="Low Angle", composition="x").shot == "over-the-shoulder"
    with pytest.raises(ValidationError):
        DirectedPanel(panel_number=1, shot="dutch tilt", angle="low", composition="x")


def test_planned_panel_sfx_are_uppercased_and_short():
    panel = PlannedPanel(panel_number=1, beat=1, purpose="p", size="small", action="a", setting="s",
                         emotion="e", sfx=["crash", "  ", "whooooooooooooooooooooooosh"])
    assert panel.sfx == ["CRASH", "WHOOOOOOOOOOOOOOOOOO"]


def test_visual_tags_prompt_skips_none():
    tags = VisualTags(hair="short black hair", eyes="sharp eyes", outfit="school uniform",
                      accessories="none", distinguishing_marks="scar on left cheek")
    assert tags.as_prompt() == "short black hair, sharp eyes, school uniform, scar on left cheek"


# --------------------------------------------------------------------------- runner
def test_runner_success_records_step():
    llm = ScriptedLLM(beat_sheet_data())
    result, step = run(llm, inputs_summary={"story_chars": 120})
    assert result.title == "Rooftop"
    assert step.status == "ok" and step.attempts == 1 and step.errors == []
    assert step.input_tokens == 1000 and step.output_tokens == 500
    assert step.cost_usd == pytest.approx((1000 * 4 + 500 * 20) / 1e6)
    assert step.output["climax_beat"] == 2 and step.inputs == {"story_chars": 120}


def test_runner_retries_on_invalid_json_then_succeeds():
    llm = ScriptedLLM("this is not json", "```json\n" + json.dumps(beat_sheet_data()) + "\n```")
    result, step = run(llm)
    assert step.attempts == 2 and len(step.errors) == 1
    assert "rejected by the validator" in llm.prompts[1]
    assert step.input_tokens == 2000  # tokens summed over attempts


def test_runner_feeds_validation_errors_back():
    llm = ScriptedLLM(beat_sheet_data(climax_beat=7), beat_sheet_data())
    run(llm)
    assert "climax_beat 7" in llm.prompts[1]


def test_runner_check_problems_are_fed_back():
    llm = ScriptedLLM(beat_sheet_data(), beat_sheet_data(title="Better"))
    checks = iter([["title must not be Rooftop"], []])
    result, step = run(llm, check=lambda r: next(checks))
    assert result.title == "Better" and "title must not be Rooftop" in llm.prompts[1]


def test_runner_gives_up_after_two_retries():
    llm = ScriptedLLM("bad", "bad", "bad", beat_sheet_data())
    with pytest.raises(AgentFailed) as info:
        run(llm)
    assert info.value.step.attempts == 3 and info.value.step.status == "failed"
    assert len(llm.answers) == 1  # the 4th answer was never requested


def test_runner_provider_error_is_not_retried():
    llm = ScriptedLLM(ProviderError("rate limited"), beat_sheet_data())
    with pytest.raises(AgentFailed, match="rate limited"):
        run(llm)


def test_cost_table_and_overrides():
    usage = TokenUsage(1_000_000, 1_000_000)
    assert cost_usd("claude-opus-5-5", usage) == 24.0
    assert cost_usd("unknown-model", usage) == 0.0
    assert cost_usd("unknown-model", usage, 1.0, 2.0) == 3.0


def test_copyright_rename_map():
    renames = rename_map(["Mira", "Pikachu"])
    assert apply("pikachu", renames) not in ("Pikachu", "pikachu", "Mira")
    assert apply("Mira", renames) == "Mira"


def test_inline_refs():
    schema = BeatSheet.model_json_schema()
    flat = inline_refs(schema)
    assert "$defs" not in json.dumps(flat) and "$ref" not in json.dumps(flat)


# --------------------------------------------------------------------------- providers
def test_gemini_provider_request_and_usage():
    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": json.dumps({"ok": True})}]}}],
            "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7}})

    provider = GeminiLLMProvider(Settings(gemini_api_key="secret-g"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = provider.generate_json(system="s", user="u", schema=BeatSheet.model_json_schema(), task="t", context={})
    assert response.data == {"ok": True} and response.usage == TokenUsage(11, 7)
    assert seen["key"] == "secret-g" and "secret-g" not in seen["url"]
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "$ref" not in json.dumps(seen["body"]["generationConfig"]["responseJsonSchema"])


def test_gemini_falls_back_when_schema_rejected():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if "responseJsonSchema" in body["generationConfig"]:
            return httpx.Response(400, json={"error": "schema unsupported"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    provider = GeminiLLMProvider(Settings(gemini_api_key="k"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.generate_json(system="s", user="u", schema={"type": "object"}, task="t", context={})
    assert len(calls) == 2 and "JSON Schema" in calls[1]["contents"][0]["parts"][0]["text"]


def test_openai_compatible_provider():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-x"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "JSON Schema" in body["messages"][0]["content"]
        return httpx.Response(200, json={"model": "llama3", "choices": [{"message": {"content": '{"a": 1}'},
                                                                           "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    provider = OpenAICompatibleLLMProvider(Settings(openai_base_url="http://local:11434/v1", openai_api_key="sk-x"),
                                           client=httpx.Client(transport=httpx.MockTransport(handler)))
    response = provider.generate_json(system="s", user="u", schema={"type": "object"}, task="t", context={})
    assert response.data == {"a": 1} and response.usage == TokenUsage(5, 3) and response.model == "llama3"


def test_openai_compatible_auth_error():
    provider = OpenAICompatibleLLMProvider(
        Settings(openai_base_url="http://x/v1", openai_api_key="k"),
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))))
    with pytest.raises(ProviderError, match="rejected the API key"):
        provider.generate_json(system="s", user="u", schema={}, task="t", context={})
