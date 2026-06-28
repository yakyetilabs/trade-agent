"""Unit test for the runner's pure report aggregation (no model)."""

from eval.run_eval import RunRow, summarize


def test_summarize_renders_accuracy_latency_and_failures() -> None:
    rows = [
        RunRow("flash", "c1", "tariff_classification", True, 3, 3, 1200.0, 140, []),
        RunRow("flash", "c2", "escalation_triggers", False, 2, 3, 90.0, None, ["includes_any"]),
        RunRow("pro", "c1", "tariff_classification", True, 3, 3, 2000.0, 260, []),
        RunRow("pro", "c2", "escalation_triggers", True, 3, 3, 95.0, None, []),
    ]
    md = summarize(rows, ["flash", "pro"])

    assert "# Eval Report" in md
    assert "tariff_classification" in md
    assert "| TOTAL |" in md
    assert "## Latency & cost" in md
    assert "c2: includes_any" in md  # the single failure is listed
    # flash total = 1/2 passed; pro total = 2/2 passed
    assert "| TOTAL | 1/2 | 2/2 |" in md
