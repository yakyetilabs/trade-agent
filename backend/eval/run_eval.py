"""Flash-vs-Pro evaluation runner (live).

Runs every case in ``cases.json`` through ``run_agent`` once per model, scores each with
the deterministic scorer, and writes a raw JSON record plus a human-readable markdown
summary to ``eval/results/`` (gitignored). This is the *live* driver: it needs Vertex +
seeded Firestore + the Pinecone KB, so it runs user-side after setup. The scoring and
schema it depends on are unit-tested hermetically (``test_scoring.py`` / ``test_schema.py``).

Usage (from ``backend/``)::

    uv run python -m eval.run_eval                 # both models, all cases
    uv run python -m eval.run_eval --models flash  # primary only
    uv run python -m eval.run_eval --category escalation_triggers
"""

import argparse
import json
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from eval.schema import EvalCase, load_cases
from eval.scoring import score_case
from src.agent import run_agent
from src.config import VERTEX_EVAL_MODEL, VERTEX_PRIMARY_MODEL

_RESULTS_DIR = Path(__file__).parent / "results"
_MODELS: dict[str, str] = {"flash": VERTEX_PRIMARY_MODEL, "pro": VERTEX_EVAL_MODEL}


@dataclass(frozen=True)
class RunRow:
    """One case run under one model - the serializable unit of a report."""

    model: str
    case_id: str
    category: str
    passed: bool
    passed_count: int
    total: int
    duration_ms: float
    total_tokens: int | None
    failed_assertions: list[str]


def run_suite(cases: Sequence[EvalCase], model_label: str, model_id: str) -> list[RunRow]:
    """Run every case under one model and score it. Errors degrade to a failed row."""
    rows: list[RunRow] = []
    for case in cases:
        try:
            result = run_agent(case.vendor_id, case.inquiry, model_id=model_id)
            score = score_case(result, case)
            rows.append(
                RunRow(
                    model=model_label,
                    case_id=case.id,
                    category=case.category.value,
                    passed=score.passed,
                    passed_count=score.passed_count,
                    total=score.total,
                    duration_ms=result.duration_ms,
                    total_tokens=result.total_tokens,
                    failed_assertions=[a.name for a in score.assertions if not a.passed],
                )
            )
        except Exception as exc:  # noqa: BLE001 - a crashing case is a (recorded) failure
            rows.append(
                RunRow(
                    model=model_label,
                    case_id=case.id,
                    category=case.category.value,
                    passed=False,
                    passed_count=0,
                    total=1,
                    duration_ms=0.0,
                    total_tokens=None,
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


def summarize(rows: Sequence[RunRow], labels: Sequence[str]) -> str:
    """Render a markdown Flash-vs-Pro report: accuracy by category, latency, cost."""
    categories = sorted({r.category for r in rows})
    lines: list[str] = [
        f"# Eval Report - {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        f"Models: {', '.join(labels)}",
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
        "| Model | mean ms | p95 ms | total tokens |",
        "|---|---|---|---|",
    ]
    for label in labels:
        subset = [r for r in rows if r.model == label]
        durations = [r.duration_ms for r in subset]
        tokens = sum(r.total_tokens or 0 for r in subset)
        mean_ms = statistics.mean(durations) if durations else 0.0
        lines.append(f"| {label} | {mean_ms:.0f} | {_percentile(durations, 95):.0f} | {tokens} |")

    failures = [r for r in rows if not r.passed]
    lines += ["", f"## Failures ({len(failures)})", ""]
    lines += [f"- [{r.model}] {r.case_id}: {', '.join(r.failed_assertions)}" for r in failures] or [
        "- none"
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Flash-vs-Pro eval runner")
    parser.add_argument("--models", default="flash,pro", help="comma list of: flash, pro")
    parser.add_argument("--category", default=None, help="run only one category")
    args = parser.parse_args()

    cases = load_cases()
    if args.category:
        cases = [c for c in cases if c.category.value == args.category]
    labels = [m.strip() for m in args.models.split(",") if m.strip()]

    all_rows: list[RunRow] = []
    for label in labels:
        print(f"Running {len(cases)} cases on {label} ({_MODELS[label]})...")
        all_rows.extend(run_suite(cases, label, _MODELS[label]))

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
