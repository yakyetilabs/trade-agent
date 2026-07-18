"""Per-MTok list prices behind the eval reports' cost estimates.

USD per 1M tokens as ``(input, output)``, keyed by CONCRETE model id - deliberately not
by config role, so a primary-model swap can never silently attach the wrong price; an id
missing here renders as ``n/a`` in reports rather than a wrong number. Output prices
cover "response and reasoning", matching ``AgentResult``'s convention that
``output_tokens`` includes ``thoughts_tokens``. Values are the <=200k-token prompt tier
(this suite's prompts sit far below the tier break).

Eval-side metadata only - nothing in the serving path reads this module. Gemini prices
verified against https://cloud.google.com/vertex-ai/generative-ai/pricing and Claude
prices against Anthropic's published per-MTok list (which Anthropic-on-Vertex matches),
both on ``PRICING_AS_OF``; re-verify before quoting the numbers anywhere durable.
"""

PRICING_AS_OF: str = "2026-07-17"

_PER_MTOK_USD: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "claude-haiku-4-5@20251001": (1.00, 5.00),
    "claude-sonnet-4-5@20250929": (3.00, 15.00),
    # The same snapshots' first-party dashed ids (the direct-API binding in
    # src/model_provider.py); Anthropic lists one price per model on either platform.
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
}


def estimate_cost_usd(model_id: str, prompt_tokens: int, output_tokens: int) -> float | None:
    """Billable USD for one run, or ``None`` when ``model_id`` has no price on file."""
    prices = _PER_MTOK_USD.get(model_id)
    if prices is None:
        return None
    input_per_mtok, output_per_mtok = prices
    return (prompt_tokens * input_per_mtok + output_tokens * output_per_mtok) / 1_000_000
