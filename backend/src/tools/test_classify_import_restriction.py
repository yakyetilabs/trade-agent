"""Unit tests for classify_import_restriction.

The single Vertex seam (``_classify_once``) is monkeypatched, so no model is
called. Tests cover the happy mapping, graceful degradation, and the security
invariant that the model-facing schema exposes only ``inquiry``.
"""

import pytest

import src.tools.classify_import_restriction as classify_mod
from src.models import InquiryIntent, RestrictionLevel
from src.tracing.trace_context import trace_context


def test_run_classify_maps_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(inquiry: str, model_id: str | None) -> classify_mod._ClassifierOutput:
        return classify_mod._ClassifierOutput(
            intent="tariff_lookup",
            confidence=0.9,
            reasoning="duty-rate question",
            proposed_hts_heading="8517",
            restriction_band="unrestricted",
        )

    monkeypatch.setattr(classify_mod, "_classify_once", fake)

    with trace_context("tr-1", "V-001") as ctx:
        result = classify_mod.run_classify_import_restriction("duty rate for phones?")

    assert result.intent is InquiryIntent.TARIFF_LOOKUP
    assert result.restriction_band is RestrictionLevel.UNRESTRICTED
    assert result.proposed_hts_heading == "8517"
    # The call was recorded on the trace with the full classification as output.
    assert ctx.tool_calls[0].tool_name == "classify_import_restriction"
    assert ctx.tool_calls[0].output["intent"] == "tariff_lookup"


def test_run_classify_degrades_to_unknown_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(inquiry: str, model_id: str | None) -> classify_mod._ClassifierOutput:
        raise RuntimeError("vertex unavailable")

    monkeypatch.setattr(classify_mod, "_classify_once", boom)

    with trace_context("tr-1", "V-001"):
        result = classify_mod.run_classify_import_restriction("anything")

    assert result.intent is InquiryIntent.UNKNOWN
    assert result.confidence == 0.0
    assert "vertex unavailable" in result.reasoning


def test_classify_tool_exposes_only_inquiry_to_the_model() -> None:
    assert set(classify_mod.classify_import_restriction.args.keys()) == {"inquiry"}
