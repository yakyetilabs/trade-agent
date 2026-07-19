"""Hermetic tests for the report aggregator - synthetic stamps, no model calls."""

import json
from pathlib import Path

import pytest

from eval.report import (
    Manifest,
    ReportRow,
    Selection,
    build_report,
    extract_between,
    guarded_case_ids,
    percentile,
    platform_for,
    provenance_errors,
    rate_cell,
)
from eval.schema import EvalCase, EvalCategory, Expect

_CASES: list[EvalCase] = [
    EvalCase(
        id="model-case",
        category=EvalCategory.HAPPY_PATH,
        vendor_id="V-001",
        inquiry="Why is my shipment held?",
        rationale="exercises the full model path",
        expect=Expect(disposition="draft"),
    ),
    EvalCase(
        id="guard-case",
        category=EvalCategory.ESCALATION_TRIGGERS,
        vendor_id="V-001",
        inquiry="Contraband question",
        rationale="guard short-circuit, zero model calls",
        expect=Expect(disposition="escalated", max_tool_calls=0),
    ),
]


def _row(
    case_id: str,
    *,
    model: str = "flash",
    model_id: str = "gemini-2.5-flash",
    category: str = "happy_path",
    prompt_tokens: int | None = 7000,
    output_tokens: int | None = 400,
    passed: bool = True,
    duration_ms: float = 20000.0,
    classifier_confidence: float | None = 0.9,
    classifier_errored: bool | None = False,
) -> ReportRow:
    total = (prompt_tokens or 0) + (output_tokens or 0)
    return ReportRow(
        model=model,
        model_id=model_id,
        case_id=case_id,
        category=category,
        passed=passed,
        passed_count=1,
        total=1,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total or None,
        assertion_results={"disposition": passed, "intent_in": passed},
        failed_assertions=[] if passed else ["disposition"],
        classifier_intent="tariff_lookup" if classifier_errored is not None else None,
        classifier_confidence=classifier_confidence,
        classifier_errored=classifier_errored,
    )


def _guard_row(case_id: str = "guard-case", *, model: str = "flash") -> ReportRow:
    return _row(
        case_id,
        model=model,
        category="escalation_triggers",
        prompt_tokens=None,
        output_tokens=None,
        duration_ms=40.0,
        classifier_confidence=None,
        classifier_errored=None,
    )


def _write_stamp(results_dir: Path, stamp: str, rows: list[ReportRow]) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    payload = [row.model_dump() for row in rows]
    (results_dir / f"{stamp}-raw.json").write_text(json.dumps(payload))


def test_guarded_case_ids_derive_from_max_tool_calls() -> None:
    assert guarded_case_ids(_CASES) == frozenset({"guard-case"})


def test_provenance_flags_zero_token_model_row() -> None:
    rows = [_row("model-case", prompt_tokens=None, output_tokens=None)]
    errors = provenance_errors(rows, frozenset({"guard-case"}))
    assert len(errors) == 1
    assert "model-case" in errors[0]
    assert "fallback" in errors[0]


def test_provenance_flags_token_bearing_guard_row() -> None:
    rows = [_row("guard-case", category="escalation_triggers")]
    errors = provenance_errors(rows, frozenset({"guard-case"}))
    assert len(errors) == 1
    assert "guard did not intercept" in errors[0]


def test_provenance_accepts_clean_rows() -> None:
    rows = [_row("model-case"), _guard_row()]
    assert provenance_errors(rows, frozenset({"guard-case"})) == []


def test_provenance_flags_degraded_classifier_despite_real_tokens() -> None:
    # The live failure mode this rule exists for: real loop tokens, dead classifier.
    rows = [_row("model-case", classifier_errored=True)]
    errors = provenance_errors(rows, frozenset({"guard-case"}))
    assert len(errors) == 1
    assert "classification stage degraded" in errors[0]


def test_provenance_tolerates_rows_predating_classifier_fields() -> None:
    # Stamps recorded before classifier health existed carry None - not an explicit
    # error, so the token rule remains their only gate.
    rows = [_row("model-case", classifier_confidence=None, classifier_errored=None)]
    assert provenance_errors(rows, frozenset({"guard-case"})) == []


def test_report_row_parses_stamps_without_classifier_fields() -> None:
    payload = _row("model-case").model_dump()
    for legacy_missing in ("classifier_intent", "classifier_confidence", "classifier_errored"):
        payload.pop(legacy_missing)
    row = ReportRow.model_validate(payload)
    assert row.classifier_errored is None


def test_platform_for_id_shapes() -> None:
    assert platform_for("gemini-2.5-flash") == "Vertex AI"
    assert platform_for("claude-haiku-4-5@20251001") == "Anthropic on Vertex AI"
    assert platform_for("claude-haiku-4-5-20251001") == "Anthropic API (direct)"
    assert platform_for("mystery-model") == "unknown"


def test_percentile_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) == 40.0
    assert percentile([], 50) == 0.0


def test_rate_cell_counts_only_evaluated_rows() -> None:
    rows = [_row("model-case"), _row("model-case", passed=False), _guard_row()]
    assert rate_cell(rows, "disposition") == "2/3 (67%)"
    assert rate_cell(rows, "never-evaluated") == "n/a"


def test_extract_between_markers() -> None:
    text = "header\n<B>\ncurated body\n<E>\nfooter"
    assert extract_between(text, "<B>", "<E>") == "curated body"
    assert extract_between(text, "<B>", "<MISSING>") is None
    assert extract_between("no markers", "<B>", "<E>") is None


def _manifest() -> Manifest:
    return Manifest(
        selections=(Selection(label="flash", stamps=("stampA", "stampB"), note="clean passes"),)
    )


def test_build_report_end_to_end(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _write_stamp(results, "stampA", [_row("model-case"), _guard_row()])
    _write_stamp(results, "stampB", [_row("model-case"), _guard_row()])

    report = build_report(_manifest(), results, _CASES, existing_text=None)

    assert "| Runs (cases x passes) | 4 |" in report
    assert "| Runs completed without crash | 4/4 |" in report
    assert "| Cases fully passed | 4/4 |" in report
    assert "| Mean classifier confidence | 0.90 |" in report
    assert "gemini-2.5-flash" in report
    assert "2 full passes" in report
    # 7000 prompt + 400 output at flash prices = $0.0031 per model-path run.
    assert "| Cost / model-path run | $0.0031 |" in report
    assert "## Scope and limitations" in report
    assert "_To be written after the next data collection pass._" in report


def test_build_report_refuses_provenance_violation(tmp_path: Path) -> None:
    results = tmp_path / "results"
    degraded = _row("model-case", prompt_tokens=None, output_tokens=None)
    _write_stamp(results, "stampA", [degraded, _guard_row()])
    _write_stamp(results, "stampB", [_row("model-case"), _guard_row()])

    with pytest.raises(ValueError, match="provenance rule violated"):
        build_report(_manifest(), results, _CASES, existing_text=None)


def test_build_report_preserves_hand_curated_sections(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _write_stamp(results, "stampA", [_row("model-case"), _guard_row()])
    _write_stamp(results, "stampB", [_row("model-case"), _guard_row()])

    first = build_report(_manifest(), results, _CASES, existing_text=None)
    curated = first.replace(
        "_To be written after the next data collection pass._",
        "Flash held disposition discipline across every pass.",
        1,  # only the findings placeholder; the conclusion keeps its placeholder
    )
    second = build_report(_manifest(), results, _CASES, existing_text=curated)

    assert "Flash held disposition discipline across every pass." in second
    assert second.count("_To be written after the next data collection pass._") == 1


def test_build_report_rejects_mixed_model_ids(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _write_stamp(results, "stampA", [_row("model-case"), _guard_row()])
    _write_stamp(
        results,
        "stampB",
        [_row("model-case", model_id="gemini-2.5-pro"), _guard_row()],
    )

    with pytest.raises(ValueError, match="mixes model ids"):
        build_report(_manifest(), results, _CASES, existing_text=None)


def test_build_report_missing_label_rows_fails_loudly(tmp_path: Path) -> None:
    results = tmp_path / "results"
    _write_stamp(results, "stampA", [_row("model-case", model="pro")])

    manifest = Manifest(
        selections=(Selection(label="flash", stamps=("stampA",), note="wrong label"),)
    )
    with pytest.raises(ValueError, match="no rows for label"):
        build_report(manifest, results, _CASES, existing_text=None)
