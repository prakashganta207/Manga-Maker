"""Token prices for the per-job cost counter (USD per million tokens).

LLM providers bill by tokens (≈ ¾ of a word each): input tokens = everything we send,
output tokens = everything the model writes. Unknown models count as $0 unless you
set LLM_INPUT_PRICE_PER_MTOK / LLM_OUTPUT_PRICE_PER_MTOK.
"""

from __future__ import annotations

from ..providers.base import TokenUsage

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
}


def cost_usd(model: str, usage: TokenUsage, input_price: float | None = None,
             output_price: float | None = None) -> float:
    known = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    p_in = input_price if input_price is not None else known[0]
    p_out = output_price if output_price is not None else known[1]
    return round((usage.input_tokens * p_in + usage.output_tokens * p_out) / 1_000_000, 6)
