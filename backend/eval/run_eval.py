"""Model-comparison evaluation runner (live).

Runs every case in ``cases.json`` through ``run_agent`` once per model label, scores each
with the deterministic scorer, and writes a raw JSON record plus a human-readable markdown
summary to ``eval/results/`` (gitignored). This is the *live* driver: it needs Vertex +
seeded Firestore + the Pinecone KB, so it runs user-side after setup. The scoring and
schema it depends on are unit-tested hermetically (``test_scoring.py`` / ``test_schema.py``).

The comparison matrix is a provider-x-tier 2x2 through the same seam: Gemini Flash (the
production model) and Pro, Claude Haiku and Sonnet on Vertex. Retrieval, tools, prompts,
and embeddings are held constant - only the agent's chat model varies per label.

Usage (from ``backend/``)::

    uv run python -m eval.run_eval                       # flash + pro, all cases
    uv run python -m eval.run_eval --models flash,haiku  # any label subset
    uv run python -m eval.run_eval --category escalation_triggers
    uv run python -m eval.run_eval --models flash --pause-seconds 45  # quota-paced
"""

import argparse
import json
import statistics
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from eval.pricing import PRICING_AS_OF, estimate_cost_usd
from eval.schema import EvalCase, load_cases
from eval.scoring import score_case
from src.agent import run_agent
from src.config import (
    CLAUDE_HAIKU_MODEL,
    CLAUDE_SONNET_MODEL,
    VERTEX_EVAL_MODEL,
    VERTEX_PRIMARY_MODEL,
)

_RESULTS_DIR = Path(__file__).parent / "results"
_MODELS: dict[str, str] = {
    "flash": VERTEX_PRIMARY_MODEL,
    "pro": VERTEX_EVAL_MODEL,
    "haiku": CLAUDE_HAIKU_MODEL,
    "sonnet": CLAUDE_SONNET_MODEL,
}


@dataclass(frozen=True)
class RunRow:
    """One case run under one model - the serializable unit of a report."""

    model: str
    model_id: str
    case_id: str
    category: str
    passed: bool
    passed_count: int
    total: int
    duration_ms: float
    prompt_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    # Every evaluated assertion name -> passed; empty when the run itself crashed, which
    # keeps crashed cases out of headline-rate denominators (they still fail the case).
    assertion_results: dict[str, bool]
    failed_assertions: list[str]


def run_suite(
    cases: Sequence[EvalCase],
    model_label: str,
    model_id: str,
    pause_seconds: float = 0.0,
) -> list[RunRow]:
    """Run every case under one model and score it. Errors degrade to a failed row.

    ``pause_seconds`` sleeps between consecutive cases: Vertex enforces per-minute
    per-base-model token quotas, and a full-speed suite tripped the flash input-TPM cap
    live (2026-07-18), silently degrading every subsequent case to a fallback draft.
    """
    rows: list[RunRow] = []
    for index, case in enumerate(cases):
        if index and pause_seconds > 0:
            time.sleep(pause_seconds)
        try:
            result = run_agent(case.vendor_id, case.inquiry, model_id=model_id)
            score = score_case(result, case)
            rows.append(
                RunRow(
                    model=model_label,
                    model_id=model_id,
                    case_id=case.id,
                    category=case.category.value,
                    passed=score.passed,
                    passed_count=score.passed_count,
                    total=score.total,
                    duration_ms=result.duration_ms,
                    prompt_tokens=result.prompt_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.total_tokens,
                    assertion_results={a.name: a.passed for a in score.assertions},
                    failed_assertions=[a.name for a in score.assertions if not a.passed],
                )
            )
        except Exception as exc:  # noqa: BLE001 - a crashing case is a (recorded) failure
            rows.append(
                RunRow(
                    model=model_label,
                    model_id=model_id,
                    case_id=case.id,
                    category=case.category.value,
                    passed=False,
                    passed_count=0,
                    total=1,
                    duration_ms=0.0,
                    prompt_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    assertion_results={},
                    failed_assertions=[f"run_error:{type(exc).__name__}"],
                )
            )
    return rows


def _percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def _rate_cell(rows: Sequence[RunRow], assertion: str) -> str:
    """``matched/evaluated (pct%)`` for one assertion, or ``n/a`` if never evaluated."""
    outcomes = [r.assertion_results[assertion] for r in rows if assertion in r.assertion_results]
    if not outcomes:
        return "n/a"
    matched = sum(outcomes)
    return f"{matched}/{len(outcomes)} ({100 * matched / len(outcomes):.0f}%)"


def _cost_cells(rows: Sequence[RunRow]) -> tuple[str, str]:
    """``(cost/run, total cost)`` cells; ``n/a`` without both a token split and a price."""
    costs: list[float] = []
    for row in rows:
        if row.prompt_tokens is None or row.output_tokens is None:
            continue
        cost = estimate_cost_usd(row.model_id, row.prompt_tokens, row.output_tokens)
        if cost is not None:
            costs.append(cost)
    if not costs:
        return "n/a", "n/a"
    return f"${statistics.mean(costs):.4f}", f"${sum(costs):.4f}"


def summarize(rows: Sequence[RunRow], labels: Sequence[str]) -> str:
    """Render a markdown model-comparison report: headline rates, accuracy, latency, cost."""
    categories = sorted({r.category for r in rows})
    model_ids: dict[str, str] = {}
    for row in rows:
        model_ids.setdefault(row.model, row.model_id)
    lines: list[str] = [
        f"# Eval Report - {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        "Models: "
        + ", ".join(
            f"{label} ({model_ids[label]})" if label in model_ids else label for label in labels
        ),
        "",
        "## Headline rates",
        "",
        "| Model | disposition match | intent match |",
        "|---|---|---|",
    ]
    for label in labels:
        subset = [r for r in rows if r.model == label]
        lines.append(
            f"| {label} | {_rate_cell(subset, 'disposition')} | {_rate_cell(subset, 'intent_in')} |"
        )

    lines += [
        "",
        "## Accuracy - cases fully passed",
        "",
        "| Category | " + " | ".join(labels) + " |",
        "|" + "---|" * (len(labels) + 1),
    ]
    for category in [*categories, "TOTAL"]:
        cells: list[str] = []
        for label in labels:
            subset = [r for r in rows if r.model == label]
            if category != "TOTAL":
                subset = [r for r in subset if r.category == category]
            passed = sum(1 for r in subset if r.passed)
            cells.append(f"{passed}/{len(subset)}")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Latency & cost",
        "",
        "| Model | mean ms | p50 ms | p95 ms | prompt tok | output tok | cost/run | total cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for label in labels:
        subset = [r for r in rows if r.model == label]
        durations = [r.duration_ms for r in subset]
        mean_ms = statistics.mean(durations) if durations else 0.0
        prompt_tok = sum(r.prompt_tokens or 0 for r in subset)
        output_tok = sum(r.output_tokens or 0 for r in subset)
        cost_per_run, cost_total = _cost_cells(subset)
        lines.append(
            f"| {label} | {mean_ms:.0f} | {_percentile(durations, 50):.0f} | "
            f"{_percentile(durations, 95):.0f} | {prompt_tok} | {output_tok} | "
            f"{cost_per_run} | {cost_total} |"
        )
    lines += ["", f"Token prices as of {PRICING_AS_OF} (eval/pricing.py); unpriced ids show n/a."]

    failures = [r for r in rows if not r.passed]
    lines += ["", f"## Failures ({len(failures)})", ""]
    lines += [f"- [{r.model}] {r.case_id}: {', '.join(r.failed_assertions)}" for r in failures] or [
        "- none"
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Model-comparison eval runner")
    parser.add_argument(
        "--models", default="flash,pro", help="comma list of: flash, pro, haiku, sonnet"
    )
    parser.add_argument("--category", default=None, help="run only one category")
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.0,
        help="sleep between cases to stay under per-minute model quotas",
    )
    args = parser.parse_args()

    cases = load_cases()
    if args.category:
        cases = [c for c in cases if c.category.value == args.category]
    labels = [m.strip() for m in args.models.split(",") if m.strip()]

    all_rows: list[RunRow] = []
    for label in labels:
        print(f"Running {len(cases)} cases on {label} ({_MODELS[label]})...")
        all_rows.extend(run_suite(cases, label, _MODELS[label], pause_seconds=args.pause_seconds))

    report = summarize(all_rows, labels)
    print("\n" + report)

    _RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (_RESULTS_DIR / f"{stamp}-raw.json").write_text(
        json.dumps([asdict(r) for r in all_rows], indent=2)
    )
    (_RESULTS_DIR / f"{stamp}-summary.md").write_text(report)
    print(f"Wrote results/{stamp}-raw.json and results/{stamp}-summary.md")


if __name__ == "__main__":
    main()
