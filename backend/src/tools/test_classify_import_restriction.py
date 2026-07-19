"""Unit tests for classify_import_restriction.

The single structured-call seam (``_classify_once``) is monkeypatched, so no model is
called. Tests cover the happy mapping, usage recording, graceful degradation (with its
machine-readable error marker), and the security invariant that the model-facing schema
exposes only ``inquiry`` - the model binding rides in the runtime context.
"""

import pytest

import src.tools.classify_import_restriction as classify_mod
from src.models import InquiryIntent, RestrictionLevel
from src.tracing.trace_context import trace_context


def _output() -> classify_mod._ClassifierOutput:
    return classify_mod._ClassifierOutput(
        intent="tariff_lookup",
        confidence=0.9,
        reasoning="duty-rate question",
        proposed_hts_heading="8517",
        restriction_band="unrestricted",
    )


def test_run_classify_maps_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(inquiry: str, model_id: str | None) -> classify_mod._ClassifierCall:
        return classify_mod._ClassifierCall(output=_output(), usage=None)

    monkeypatch.setattr(classify_mod, "_classify_once", fake)

    with trace_context("tr-1", "V-001") as ctx:
        result = classify_mod.run_classify_import_restriction("duty rate for phones?")

    assert result.intent is InquiryIntent.TARIFF_LOOKUP
    assert result.restriction_band is RestrictionLevel.UNRESTRICTED
    assert result.proposed_hts_heading == "8517"
    # The call was recorded on the trace with the full classification as output.
    assert ctx.tool_calls[0].tool_name == "classify_import_restriction"
    assert ctx.tool_calls[0].output["intent"] == "tariff_lookup"
    # No usage returned by the provider -> none recorded (never a fake all-zero split).
    assert "usage" not in ctx.tool_calls[0].output


def test_run_classify_records_call_usage_on_the_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = {"input_tokens": 310, "output_tokens": 55, "total_tokens": 365}

    def fake(inquiry: str, model_id: str | None) -> classify_mod._ClassifierCall:
        return classify_mod._ClassifierCall(output=_output(), usage=dict(usage))

    monkeypatch.setattr(classify_mod, "_classify_once", fake)

    with trace_context("tr-1", "V-001") as ctx:
        classify_mod.run_classify_import_restriction("duty rate for phones?")

    # Recorded under its own key: build_run_trace folds it into the run's billable split.
    assert ctx.tool_calls[0].output["usage"] == usage


def test_run_classify_forwards_the_bound_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    def fake(inquiry: str, model_id: str | None) -> classify_mod._ClassifierCall:
        seen.append(model_id)
        return classify_mod._ClassifierCall(output=_output(), usage=None)

    monkeypatch.setattr(classify_mod, "_classify_once", fake)

    with trace_context("tr-1", "V-001"):
        classify_mod.run_classify_import_restriction("anything", model_id="gemini-2.5-pro")

    # The eval arm's binding reaches the structured call - the classifier must run on the
    # same model as the loop, or a comparison arm is a silent hybrid.
    assert seen == ["gemini-2.5-pro"]


def test_run_classify_degrades_to_unknown_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(inquiry: str, model_id: str | None) -> classify_mod._ClassifierCall:
        raise RuntimeError("vertex unavailable")

    monkeypatch.setattr(classify_mod, "_classify_once", boom)

    with trace_context("tr-1", "V-001"):
        result = classify_mod.run_classify_import_restriction("anything")

    assert result.intent is InquiryIntent.UNKNOWN
    assert result.confidence == 0.0
    assert "vertex unavailable" in result.reasoning
    # The degraded reasoning starts with the shared marker - the contract the eval's
    # classifier-health provenance check keys on.
    assert result.reasoning.startswith(classify_mod.CLASSIFIER_ERROR_PREFIX)


def test_classify_tool_exposes_only_inquiry_to_the_model() -> None:
    # The runtime (vendor scope + model binding) is injected, never model-facing: the
    # LLM has no slot to redirect the classifier onto another model or vendor.
    assert set(classify_mod.classify_import_restriction.args.keys()) == {"inquiry"}
