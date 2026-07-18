"""Unit tests for the eval-side price table (no I/O)."""

from eval.pricing import estimate_cost_usd


def test_cost_scales_linearly_with_tokens() -> None:
    single = estimate_cost_usd("gemini-2.5-flash", 1_000_000, 500_000)
    doubled = estimate_cost_usd("gemini-2.5-flash", 2_000_000, 1_000_000)
    assert single is not None and single > 0
    assert doubled is not None
    assert abs(doubled - 2 * single) < 1e-9


def test_zero_tokens_cost_zero() -> None:
    assert estimate_cost_usd("gemini-2.5-pro", 0, 0) == 0.0


def test_unknown_model_id_has_no_price() -> None:
    assert estimate_cost_usd("model-with-no-price", 1_000, 1_000) is None


def test_claude_snapshot_priced_identically_on_both_platforms() -> None:
    # The Vertex "@" id and the first-party dashed id are the same snapshot; a run must
    # cost the same no matter which platform binding served it.
    for vertex_id, direct_id in [
        ("claude-haiku-4-5@20251001", "claude-haiku-4-5-20251001"),
        ("claude-sonnet-4-5@20250929", "claude-sonnet-4-5-20250929"),
    ]:
        vertex_cost = estimate_cost_usd(vertex_id, 1_000_000, 100_000)
        direct_cost = estimate_cost_usd(direct_id, 1_000_000, 100_000)
        assert vertex_cost is not None
        assert vertex_cost == direct_cost
