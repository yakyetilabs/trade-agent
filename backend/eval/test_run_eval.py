"""Unit test for the runner's pure report aggregation (no model)."""

from eval.run_eval import RunRow, summarize


def test_summarize_renders_accuracy_latency_and_failures() -> None:
    rows = [
        RunRow("haiku", "c1", "exact_hts_fetch", True, 3, 3, 1200.0, 140, []),
        RunRow("haiku", "c2", "escalation_triggers", False, 2, 3, 90.0, None, ["includes_any"]),
        RunRow("sonnet", "c1", "exact_hts_fetch", True, 3, 3, 2000.0, 260, []),
        RunRow("sonnet", "c2", "escalation_triggers", True, 3, 3, 95.0, None, []),
    ]
    md = summarize(rows, ["haiku", "sonnet"])

    assert "# Eval Report" in md
    assert "exact_hts_fetch" in md
    assert "| TOTAL |" in md
    assert "## Latency & cost" in md
    assert "c2: includes_any" in md  # the single failure is listed
    # haiku total = 1/2 passed; sonnet total = 2/2 passed
    assert "| TOTAL | 1/2 | 2/2 |" in md
