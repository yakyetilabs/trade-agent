"""Unit tests for the runner's pure report aggregation and pacing (no model)."""

from types import SimpleNamespace

import pytest

import eval.run_eval as run_eval
from eval.pricing import estimate_cost_usd
from eval.run_eval import RunRow, run_suite, summarize
from eval.schema import load_cases


def _row(
    model: str,
    case_id: str,
    *,
    model_id: str = "test-model",
    category: str = "exact_hts_fetch",
    passed: bool = True,
    passed_count: int = 3,
    total: int = 3,
    duration_ms: float = 1000.0,
    prompt_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    assertion_results: dict[str, bool] | None = None,
    failed_assertions: list[str] | None = None,
) -> RunRow:
    return RunRow(
        model=model,
        model_id=model_id,
        case_id=case_id,
        category=category,
        passed=passed,
        passed_count=passed_count,
        total=total,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        assertion_results=assertion_results if assertion_results is not None else {},
        failed_assertions=failed_assertions if failed_assertions is not None else [],
    )


def _cost(model_id: str, prompt_tokens: int, output_tokens: int) -> float:
    cost = estimate_cost_usd(model_id, prompt_tokens, output_tokens)
    assert cost is not None
    return cost


def test_summarize_renders_headline_accuracy_latency_and_failures() -> None:
    rows = [
        _row(
            "flash",
            "c1",
            model_id="gemini-2.5-flash",
            duration_ms=1200.0,
            prompt_tokens=10_000,
            output_tokens=2_000,
            total_tokens=12_000,
            assertion_results={"disposition": True, "intent_in": True},
        ),
        _row(
            "flash",
            "c2",
            model_id="gemini-2.5-flash",
            category="escalation_triggers",
            passed=False,
            passed_count=2,
            duration_ms=90.0,
            # No intent_in here: flash's intent denominator must be 1, not 2.
            assertion_results={"disposition": False, "tool_absent:x": True, "cites:y": True},
            failed_assertions=["disposition"],
        ),
        _row(
            "pro",
            "c1",
            model_id="gemini-2.5-pro",
            duration_ms=2000.0,
            prompt_tokens=2_000,
            output_tokens=200,
            total_tokens=2_200,
            assertion_results={"disposition": True, "intent_in": True},
        ),
        _row(
            "pro",
            "c2",
            model_id="gemini-2.5-pro",
            category="escalation_triggers",
            duration_ms=100.0,
            prompt_tokens=500,
            output_tokens=50,
            total_tokens=550,
            assertion_results={"disposition": True, "intent_in": True},
        ),
    ]
    md = summarize(rows, ["flash", "pro"])

    assert "# Eval Report" in md
    # The header records the concrete model id behind each label.
    assert "Models: flash (gemini-2.5-flash), pro (gemini-2.5-pro)" in md

    # Headline rates aggregate per-assertion outcomes across each label's rows.
    assert "## Headline rates" in md
    assert "| flash | 1/2 (50%) | 1/1 (100%) |" in md
    assert "| pro | 2/2 (100%) | 2/2 (100%) |" in md

    assert "exact_hts_fetch" in md
    assert "| TOTAL | 1/2 | 2/2 |" in md

    # Latency & cost: mean/p50/p95 over durations, token sums, and priced cost cells.
    flash_cost = _cost("gemini-2.5-flash", 10_000, 2_000)
    flash_cells = f"${flash_cost:.4f}", f"${flash_cost:.4f}"  # one priced run: mean == total
    assert f"| flash | 645 | 90 | 1200 | 10000 | 2000 | {flash_cells[0]} | {flash_cells[1]} |" in md
    pro_c1 = _cost("gemini-2.5-pro", 2_000, 200)
    pro_c2 = _cost("gemini-2.5-pro", 500, 50)
    pro_cells = f"${(pro_c1 + pro_c2) / 2:.4f}", f"${pro_c1 + pro_c2:.4f}"
    assert f"| pro | 1050 | 100 | 2000 | 2500 | 250 | {pro_cells[0]} | {pro_cells[1]} |" in md
    assert "Token prices as of" in md

    assert "[flash] c2: disposition" in md  # the single failure is listed


def test_summarize_degraded_and_unpriced_rows_render_na() -> None:
    rows = [
        _row(
            "flash",
            "c1",
            passed=False,
            passed_count=0,
            total=1,
            duration_ms=0.0,
            assertion_results={},  # crashed run: never scored
            failed_assertions=["run_error:ValueError"],
        ),
    ]
    md = summarize(rows, ["flash"])

    assert "Models: flash (test-model)" in md
    # A crashed run contributes to no headline denominator, and an unpriced
    # model id ("test-model") yields n/a cost cells rather than a wrong number.
    assert "| flash | n/a | n/a |" in md
    assert "| flash | 0 | 0 | 0 | 0 | 0 | n/a | n/a |" in md
    assert "[flash] c1: run_error:ValueError" in md


def test_run_suite_records_classifier_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each row carries the classification stage's intent/confidence/error marker.

    The error flag keys on CLASSIFIER_ERROR_PREFIX - the contract the report's
    provenance check uses to reject rows whose classification silently degraded.
    """
    cases = load_cases()[:2]
    healthy = SimpleNamespace(
        intent=SimpleNamespace(value="tariff_lookup"), confidence=0.91, reasoning="clear ask"
    )
    degraded = SimpleNamespace(
        intent=SimpleNamespace(value="unknown"),
        confidence=0.0,
        reasoning=f"{run_eval.CLASSIFIER_ERROR_PREFIX} 429 RESOURCE_EXHAUSTED",
    )
    results = iter(
        SimpleNamespace(
            duration_ms=1.0,
            prompt_tokens=1,
            output_tokens=1,
            total_tokens=2,
            classification=classification,
        )
        for classification in (healthy, degraded)
    )
    score = SimpleNamespace(passed=True, passed_count=1, total=1, assertions=[])
    monkeypatch.setattr(run_eval, "run_agent", lambda *a, **k: next(results))
    monkeypatch.setattr(run_eval, "score_case", lambda *a: score)

    rows = run_suite(cases, "flash", "test-model")

    assert (rows[0].classifier_intent, rows[0].classifier_errored) == ("tariff_lookup", False)
    assert rows[0].classifier_confidence == 0.91
    assert (rows[1].classifier_intent, rows[1].classifier_errored) == ("unknown", True)


def test_run_suite_paces_between_cases_but_not_before_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = load_cases()[:3]
    result = SimpleNamespace(
        duration_ms=1.0, prompt_tokens=1, output_tokens=1, total_tokens=2, classification=None
    )
    score = SimpleNamespace(passed=True, passed_count=1, total=1, assertions=[])
    sleeps: list[float] = []
    monkeypatch.setattr(run_eval, "run_agent", lambda *a, **k: result)
    monkeypatch.setattr(run_eval, "score_case", lambda *a: score)
    monkeypatch.setattr(run_eval.time, "sleep", sleeps.append)

    rows = run_suite(cases, "flash", "test-model", pause_seconds=45.0)

    # N cases -> N-1 pauses: the sleep separates consecutive cases only, keeping each
    # minute's quota spend to roughly one case.
    assert len(rows) == 3
    assert sleeps == [45.0, 45.0]

    sleeps.clear()
    run_suite(cases, "flash", "test-model")
    assert sleeps == []  # default stays full speed
