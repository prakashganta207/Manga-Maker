"""Run one agent step: prompt -> LLM (structured JSON) -> Pydantic validation -> retry.

Every call produces an `AgentStep` record (inputs, output, retries, errors, duration,
tokens, cost) that is stored in the job state and shown in the Agent timeline.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, Field, ValidationError

from ..providers.base import LLMProvider, ProviderError, TokenUsage
from .cost import cost_usd

log = logging.getLogger("manga.agents")

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 2  # so up to 3 attempts in total


class AgentStep(BaseModel):
    """One agent's work, as shown in the Agent timeline."""

    agent: str                      # "writer", "director", "character_designer", ...
    label: str                      # human-friendly title, e.g. "Beat sheet"
    started_at: str = ""
    duration_s: float = 0.0
    status: str = "ok"              # ok | failed | skipped
    attempts: int = 0
    errors: list[str] = Field(default_factory=list)  # validation errors that caused retries
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    inputs: dict[str, Any] = Field(default_factory=dict)   # short summary of what the agent got
    output: Any = None                                      # the validated JSON
    notes: list[str] = Field(default_factory=list)          # e.g. rule fixes applied in code


class AgentFailed(RuntimeError):
    def __init__(self, message: str, step: AgentStep):
        super().__init__(message)
        self.step = step


def parse_json(raw: Any) -> dict[str, Any]:
    """Accept a dict, or a JSON string (optionally wrapped in ```json fences)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    raise ValueError("The answer is not a JSON object")


def error_list(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def with_feedback(user: str, errors: list[str]) -> str:
    # Repair loop: show the model exactly what was wrong with its previous answer.
    return (user + "\n\nYour previous answer was rejected by the validator:\n- "
            + "\n- ".join(errors[:15]) + "\nReturn a corrected, complete JSON answer.")


def run_agent(
    *,
    agent: str,
    label: str,
    llm: LLMProvider,
    system: str,
    user: str,
    output_model: type[T],
    task: str,
    context: dict[str, Any],
    inputs_summary: dict[str, Any] | None = None,
    check: Callable[[T], list[str]] | None = None,
    max_retries: int = MAX_RETRIES,
    prices: tuple[float | None, float | None] = (None, None),
) -> tuple[T, AgentStep]:
    """Call the LLM until the answer validates (schema + optional `check`).

    `check(result)` returns a list of problems (cross-checks against earlier agents);
    problems are fed back to the LLM exactly like schema errors.
    """
    step = AgentStep(agent=agent, label=label, inputs=inputs_summary or {},
                     started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    schema = output_model.model_json_schema()
    usage = TokenUsage()
    started = time.monotonic()
    errors: list[str] = []
    prompt = user

    for attempt in range(1, max_retries + 2):
        step.attempts = attempt
        try:
            response = llm.generate_json(system=system, user=prompt, schema=schema, task=task, context=context)
        except ProviderError as exc:
            step.status, step.errors = "failed", step.errors + [str(exc)]
            _finish(step, usage, started, llm, prices)
            raise AgentFailed(f"{label}: {exc}", step) from exc
        usage = usage + response.usage
        step.model = response.model or getattr(llm, "model", "") or llm.name
        try:
            result = output_model.model_validate(parse_json(response.data))
            problems = check(result) if check else []
            if problems:
                raise ValueError("; ".join(problems))
        except (ValidationError, ValueError) as exc:  # JSONDecodeError is a ValueError
            errors = error_list(exc)
            step.errors.extend(f"attempt {attempt}: {e}" for e in errors)
            log.info("%s attempt %d rejected: %s", label, attempt, errors[:3])
            prompt = with_feedback(user, errors)
            continue
        step.output = result.model_dump(mode="json")
        _finish(step, usage, started, llm, prices)
        return result, step

    step.status = "failed"
    _finish(step, usage, started, llm, prices)
    raise AgentFailed(f"{label}: no valid answer after {step.attempts} attempts: {'; '.join(errors[:5])}", step)


def _finish(step: AgentStep, usage: TokenUsage, started: float, llm: LLMProvider,
            prices: tuple[float | None, float | None]) -> None:
    step.duration_s = round(time.monotonic() - started, 3)
    step.input_tokens, step.output_tokens = usage.input_tokens, usage.output_tokens
    step.cost_usd = cost_usd(step.model, usage, *prices) if llm.name != "mock" else 0.0
    log.info("agent=%s label=%s attempts=%d tokens_in=%d tokens_out=%d cost=$%.4f",
             step.agent, step.label, step.attempts, step.input_tokens, step.output_tokens, step.cost_usd)
