"""Aggregate manifest-chosen eval stamps into the tracked showcase report.

``run_eval`` writes one gitignored stamp pair (``*-raw.json`` + ``*-summary.md``) per
invocation to ``eval/results/``. This module aggregates the stamps named in
``report_manifest.json`` into ``docs/EVAL_REPORT.md`` - the single tracked, curated
exception to the results-stay-local rule. Tables and methodology text are generated;
the "Notable findings" and "Conclusion" sections are hand-curated and preserved verbatim
between HTML-comment markers across regenerations.

Aggregation refuses corrupt data instead of averaging over it: every row must satisfy
the token-provenance rule (a model-dependent row records a real prompt/output split; a
pre-model-guarded row records zero), so a stamp whose runs silently degraded to fallback
drafts can never contribute numbers. Pure aggregation - no model calls, no env needed::

    uv run python -m eval.report
"""

import argparse
import json
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from eval.pricing import PRICING_AS_OF, estimate_cost_usd
from eval.schema import EvalCase, load_cases

_REPO_ROOT = Path(__file__).parents[2]
_DEFAULT_MANIFEST = Path(__file__).parent / "report_manifest.json"
_DEFAULT_RESULTS_DIR = Path(__file__).parent / "results"
_DEFAULT_OUTPUT = _REPO_ROOT / "docs" / "EVAL_REPORT.md"

_FINDINGS_BEGIN = "<!-- HAND-CURATED:NOTABLE-FINDINGS:BEGIN -->"
_FINDINGS_END = "<!-- HAND-CURATED:NOTABLE-FINDINGS:END -->"
_CONCLUSION_BEGIN = "<!-- HAND-CURATED:CONCLUSION:BEGIN -->"
_CONCLUSION_END = "<!-- HAND-CURATED:CONCLUSION:END -->"
_PLACEHOLDER = "_To be written after the next data collection pass._"


class ReportRow(BaseModel):
    """One case run under one model, as serialized by ``run_eval`` into ``*-raw.json``.

    Mirrors ``run_eval.RunRow`` field-for-field but is parsed independently so this
    module stays import-light (no agent, no SDK clients, no env); ``extra="forbid"``
    turns any schema drift between writer and reader into a loud failure.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    assertion_results: dict[str, bool]
    failed_assertions: list[str]
    # Classifier health (see run_eval.RunRow). Defaulted so stamps recorded before these
    # fields existed still parse; the provenance check only rejects an explicit ``True``.
    classifier_intent: str | None = None
    classifier_confidence: float | None = None
    classifier_errored: bool | None = None


class Selection(BaseModel):
    """One model arm of the report: which label, aggregated from which stamps."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    stamps: tuple[str, ...]
    note: str


class Manifest(BaseModel):
    """The tracked record of which stamps feed the report - provenance made explicit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selections: tuple[Selection, ...]


def load_manifest(path: Path) -> Manifest:
    """Load and validate ``report_manifest.json``."""
    return Manifest.model_validate(json.loads(path.read_text()))


def load_selection_rows(selection: Selection, results_dir: Path) -> list[ReportRow]:
    """Load the selection's rows: each stamp's raw file, filtered to the label's rows."""
    rows: list[ReportRow] = []
    for stamp in selection.stamps:
        raw_path = results_dir / f"{stamp}-raw.json"
        stamp_rows = [ReportRow.model_validate(r) for r in json.loads(raw_path.read_text())]
        labeled = [r for r in stamp_rows if r.model == selection.label]
        if not labeled:
            raise ValueError(f"stamp {stamp} has no rows for label {selection.label!r}")
        rows.extend(labeled)
    return rows


def guarded_case_ids(cases: Sequence[EvalCase]) -> frozenset[str]:
    """Case ids intercepted before any model call (``expect.max_tool_calls == 0``)."""
    return frozenset(c.id for c in cases if c.expect.max_tool_calls == 0)


def provenance_errors(rows: Sequence[ReportRow], guarded: frozenset[str]) -> list[str]:
    """Provenance violations: the tells for runs that silently degraded.

    Token rule: a run that reached the model always records a real token split; a
    pre-model-guarded run never consumes any. A zero-token model-dependent row is
    fallback text wearing a completed status, and a token-bearing guard row means the
    guard did not intercept. Classifier rule: a model-dependent row whose classification
    degraded to the recorded error marker never carried a model opinion, even when its
    token split is real (observed live: an upstream 429 inside otherwise-healthy runs).
    """
    errors: list[str] = []
    for row in rows:
        if row.case_id in guarded:
            if row.total_tokens:
                errors.append(
                    f"[{row.model}] {row.case_id}: guard case recorded"
                    f" {row.total_tokens} tokens (guard did not intercept)"
                )
            continue
        if not row.prompt_tokens or not row.output_tokens:
            errors.append(
                f"[{row.model}] {row.case_id}: model-dependent row without a real"
                " token split (degraded to a fallback draft, never reached the model)"
            )
        if row.classifier_errored:
            errors.append(
                f"[{row.model}] {row.case_id}: classification stage degraded to an"
                " error fallback (the row measures a broken pipeline, not the model)"
            )
    return errors


def platform_for(model_id: str) -> str:
    """Human-readable serving platform, derived from the id shape (see model_provider)."""
    if model_id.startswith("gemini"):
        return "Vertex AI"
    if model_id.startswith("claude-"):
        return "Anthropic on Vertex AI" if "@" in model_id else "Anthropic API (direct)"
    return "unknown"


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile, matching ``run_eval``'s convention exactly."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def rate_cell(rows: Sequence[ReportRow], assertion: str) -> str:
    """``matched/evaluated (pct%)`` for one assertion, or ``n/a`` if never evaluated."""
    outcomes = [r.assertion_results[assertion] for r in rows if assertion in r.assertion_results]
    if not outcomes:
        return "n/a"
    matched = sum(outcomes)
    return f"{matched}/{len(outcomes)} ({100 * matched / len(outcomes):.0f}%)"


def extract_between(text: str, begin: str, end: str) -> str | None:
    """The hand-curated block between two markers, or ``None`` when absent/malformed."""
    begin_at = text.find(begin)
    end_at = text.find(end)
    if begin_at == -1 or end_at == -1 or end_at < begin_at:
        return None
    return text[begin_at + len(begin) : end_at].strip("\n")


def _mean_cost_usd(rows: Sequence[ReportRow]) -> float | None:
    costs: list[float] = []
    for row in rows:
        if row.prompt_tokens is None or row.output_tokens is None:
            continue
        cost = estimate_cost_usd(row.model_id, row.prompt_tokens, row.output_tokens)
        if cost is not None:
            costs.append(cost)
    return statistics.mean(costs) if costs else None


def _model_id_of(rows: Sequence[ReportRow], label: str) -> str:
    ids = {r.model_id for r in rows}
    if len(ids) != 1:
        raise ValueError(f"label {label!r} mixes model ids across stamps: {sorted(ids)}")
    return ids.pop()


def build_report(
    manifest: Manifest,
    results_dir: Path,
    cases: Sequence[EvalCase],
    existing_text: str | None,
) -> str:
    """Render the full report. Raises on any provenance violation - never averages it."""
    guarded = guarded_case_ids(cases)
    labels = [s.label for s in manifest.selections]
    rows_by_label: dict[str, list[ReportRow]] = {}
    for selection in manifest.selections:
        rows = load_selection_rows(selection, results_dir)
        errors = provenance_errors(rows, guarded)
        if errors:
            raise ValueError(
                "provenance rule violated - refusing to aggregate:\n" + "\n".join(errors)
            )
        rows_by_label[selection.label] = rows

    model_ids = {label: _model_id_of(rows_by_label[label], label) for label in labels}
    categories = list(dict.fromkeys(c.category.value for c in cases))
    findings = existing_text and extract_between(existing_text, _FINDINGS_BEGIN, _FINDINGS_END)
    conclusion = existing_text and extract_between(
        existing_text, _CONCLUSION_BEGIN, _CONCLUSION_END
    )

    lines: list[str] = [
        "# Eval report: TradeOps AI model comparison",
        "",
        "<!-- Generated by backend/eval/report.py - do not edit outside the marked",
        "     hand-curated sections; regenerate with: uv run python -m eval.report -->",
        "",
        "## Setup",
        "",
        f"- **Generated:** {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- **Cases:** {len(cases)} across {len(categories)} categories"
        " (version-controlled in `backend/eval/cases.json`)",
        "- **Models compared:**",
    ]
    for label in labels:
        selection = next(s for s in manifest.selections if s.label == label)
        lines.append(
            f"  - `{label}` = `{model_ids[label]}` on {platform_for(model_ids[label])},"
            f" {len(selection.stamps)} full passes"
        )
    lines += [
        "- **Methodology:** every arm runs the identical LangGraph agent through the single"
        " provider seam (`backend/src/model_provider.py`): same system prompt, same four"
        " tools, same Pinecone retrieval and embeddings, temperature 0 everywhere.",
        "  The arm's model serves both the agent loop and the classifier's structured-output"
        " call, so each arm is measured end to end on one model and nothing else varies.",
        "  Cases are paced 60 seconds apart so provider per-minute admission limits stay"
        " out of the measurement.",
        "  Each pass is a separate full-suite run; per-model numbers aggregate all of that"
        " model's passes.",
        "",
        "## Data integrity",
        "",
        "Every aggregated row passed two provenance rules.",
        "Token rule: a model-dependent row must record a real prompt/output token split"
        " (a run that reached the model always consumes tokens), and a pre-model-guarded"
        " row must record zero.",
        "Classifier rule: a model-dependent row must carry a healthy classification -"
        " a run whose classification stage degraded to its error fallback measures a"
        " broken pipeline, not a model, even when its own token split is real.",
        "A stamp that fails either rule is discarded whole for the affected model, never"
        " patched or averaged over; the generator enforces both mechanically and refuses"
        " to aggregate on any violation.",
        "",
    ]
    for selection in manifest.selections:
        stamp_list = ", ".join(f"`{s}`" for s in selection.stamps)
        lines.append(f"- **{selection.label}** ({stamp_list}): {selection.note}")
    lines += [
        "",
        "## Headline numbers",
        "",
        "| Metric | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]

    metric_cells: dict[str, dict[str, str]] = {}
    for label in labels:
        rows = rows_by_label[label]
        model_rows = [r for r in rows if r.case_id not in guarded]
        guard_rows = [r for r in rows if r.case_id in guarded]
        durations = [r.duration_ms for r in model_rows]
        mean_cost = _mean_cost_usd(model_rows)
        crash_free = sum(
            1 for r in rows if not any(a.startswith("run_error:") for a in r.failed_assertions)
        )
        confidences = [
            r.classifier_confidence for r in model_rows if r.classifier_confidence is not None
        ]
        cells = {
            "Runs (cases x passes)": str(len(rows)),
            "Runs completed without crash": f"{crash_free}/{len(rows)}",
            "Cases fully passed": f"{sum(1 for r in rows if r.passed)}/{len(rows)}",
            "Disposition match": rate_cell(rows, "disposition"),
            "Intent match": rate_cell(rows, "intent_in"),
            "Mean classifier confidence": (
                f"{statistics.mean(confidences):.2f}" if confidences else "n/a"
            ),
            "Model-path mean latency": (
                f"{statistics.mean(durations):.0f}ms" if durations else "n/a"
            ),
            "Model-path p50 latency": f"{percentile(durations, 50):.0f}ms",
            "Model-path p95 latency": f"{percentile(durations, 95):.0f}ms",
            "Guard-path mean latency": (
                f"{statistics.mean([r.duration_ms for r in guard_rows]):.0f}ms"
                if guard_rows
                else "n/a"
            ),
            "Mean prompt tokens / run": (
                f"{statistics.mean([r.prompt_tokens or 0 for r in model_rows]):.0f}"
                if model_rows
                else "n/a"
            ),
            "Mean output tokens / run": (
                f"{statistics.mean([r.output_tokens or 0 for r in model_rows]):.0f}"
                if model_rows
                else "n/a"
            ),
            "Cost / model-path run": f"${mean_cost:.4f}" if mean_cost is not None else "n/a",
        }
        metric_cells[label] = cells
    for metric in next(iter(metric_cells.values())):
        cells = [metric_cells[label][metric] for label in labels]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Latency is split by path on purpose: the two deterministic guard categories"
        " resolve before any model call, so folding their near-instant runs into one"
        " average would flatter every model.",
        "",
        "## Per-category accuracy (cases fully passed)",
        "",
        "| Category | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for category in [*categories, "TOTAL"]:
        cells = []
        for label in labels:
            subset = rows_by_label[label]
            if category != "TOTAL":
                subset = [r for r in subset if r.category == category]
            cells.append(f"{sum(1 for r in subset if r.passed)}/{len(subset)}")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Per-category mean latency",
        "",
        "| Category | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for category in categories:
        cells = []
        for label in labels:
            subset = [r for r in rows_by_label[label] if r.category == category]
            cells.append(f"{statistics.mean([r.duration_ms for r in subset]):.0f}ms")
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Per-category mean classifier confidence",
        "",
        "| Category | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for category in categories:
        cells = []
        for label in labels:
            subset = [
                r
                for r in rows_by_label[label]
                if r.category == category and r.classifier_confidence is not None
            ]
            cells.append(
                f"{statistics.mean([r.classifier_confidence or 0.0 for r in subset]):.2f}"
                if subset
                else "n/a"
            )
        lines.append(f"| {category} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Confidence is the classifier's own calibrated estimate (0-1)."
        " Escalation-guard rows have no classification (the model never ran), and"
        " cross-vendor rows carry the deterministic guard's injected 1.00; n/a marks"
        " cells with no recorded value (stamps predating this field).",
    ]

    lines += [
        "",
        "## Unit economics",
        "",
        "| Model | Cost / inquiry | Cost / 1,000 inquiries | Eval total |",
        "|---|---|---|---|",
    ]
    for label in labels:
        model_rows = [r for r in rows_by_label[label] if r.case_id not in guarded]
        mean_cost = _mean_cost_usd(model_rows)
        if mean_cost is None:
            lines.append(f"| {label} | n/a | n/a | n/a |")
            continue
        total = sum(
            estimate_cost_usd(r.model_id, r.prompt_tokens or 0, r.output_tokens or 0) or 0.0
            for r in model_rows
        )
        lines.append(f"| {label} | ~${mean_cost:.4f} | ~${mean_cost * 1000:.2f} | ${total:.4f} |")
    lines += [
        "",
        f"Token prices per concrete model id as of {PRICING_AS_OF} (`backend/eval/pricing.py`);"
        " an id without a price on file renders n/a rather than a wrong number.",
        "Token totals cover every model call in a run - the agent loop and the classifier's"
        " structured-output call - summed from provider-reported usage, with one known"
        " exception recorded in the erratum under Notable findings: a run stopped by the"
        " iteration cap records only its classifier call, so the affected arms' figures are"
        " low. Runs from 2026-07-22 onward are unaffected.",
        "Guard-intercepted inquiries cost $0.00 by construction and are excluded from the"
        " per-inquiry figures, which cover the model path only.",
    ]
    if any(platform_for(model_ids[label]) == "Anthropic API (direct)" for label in labels):
        lines += [
            "",
            "Latency across arms served by different platforms carries a serving-platform"
            " confound (network path and serving stack differ, not just the model); compare"
            " p50s across platforms directionally, not as a benchmark.",
        ]

    lines += [
        "",
        "## Scope and limitations",
        "",
        "- Runs execute the agent in-process on a workstation, not against the deployed"
        " endpoint: the public API deliberately exposes no model-selection parameter"
        " (abuse-containment posture), so comparison arms can only be bound in-process.",
        "  Latency figures are therefore comparative across arms under identical local"
        " conditions - they include retrieval, Firestore, and model round-trips - and are"
        " not serving-path SLOs.",
        f"- The suite is {len(cases)} hand-curated, grounded cases across"
        f" {len(categories)} capability categories; repeat passes at temperature 0"
        " measure stability, not sampled variance, and no statistical significance is"
        " claimed.",
        "- The scorer asserts mechanically checkable properties (disposition, tool"
        " sequence, citation grounding, key phrasing); overall draft prose quality is not"
        " graded by humans or by a judge model.",
        "",
        "## Notable findings",
        "",
        _FINDINGS_BEGIN,
        findings or _PLACEHOLDER,
        _FINDINGS_END,
        "",
        "## Conclusion",
        "",
        _CONCLUSION_BEGIN,
        conclusion or _PLACEHOLDER,
        _CONCLUSION_END,
        "",
        "## Reproducing",
        "",
        "```bash",
        "cd backend",
        "uv run --env-file .env python -m eval.run_eval --models flash --pause-seconds 60",
        "uv run python -m eval.report  # aggregates the stamps named in report_manifest.json",
        "```",
        "",
        "Raw per-run stamps live in `backend/eval/results/` (deliberately untracked);"
        " `backend/eval/report_manifest.json` records exactly which stamps feed this report.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate eval stamps into docs/EVAL_REPORT.md")
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    parser.add_argument("--results-dir", type=Path, default=_DEFAULT_RESULTS_DIR)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    existing = args.output.read_text() if args.output.exists() else None
    report = build_report(manifest, args.results_dir, load_cases(), existing)
    args.output.write_text(report)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
