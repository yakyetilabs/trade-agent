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
