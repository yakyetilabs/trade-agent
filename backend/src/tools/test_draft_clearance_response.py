"""Unit tests for draft_clearance_response (signals only, no persistence)."""

import src.tools.draft_clearance_response as draft_mod
from src.tracing.trace_context import get_current_trace, trace_context


def test_draft_signals_on_trace_and_returns_trace_id() -> None:
    with trace_context("tr-42", "V-001") as ctx:
        result = draft_mod.run_draft_clearance_response(
            response_text="Shipment S-2000 is held pending an import license.",
            cited_hts_codes=["8517.13.0000"],
            cited_shipment_ids=["S-2000"],
            confidence=0.88,
        )

    assert result == {"trace_id": "tr-42", "status": "drafted"}
    # The draft text is recorded as tool-call INPUT (the loop reads it from here).
    recorded = ctx.tool_calls[0]
    assert recorded.tool_name == "draft_clearance_response"
    assert recorded.input["response_text"].startswith("Shipment S-2000")  # type: ignore[union-attr]


def test_draft_outside_trace_returns_no_trace_sentinel() -> None:
    assert get_current_trace() is None
    result = draft_mod.run_draft_clearance_response(
        response_text="x",
        cited_hts_codes=[],
        cited_shipment_ids=[],
        confidence=0.5,
    )
    assert result["trace_id"] == "no-trace"


def test_draft_tool_exposes_expected_fields_to_the_model() -> None:
    assert set(draft_mod.draft_clearance_response.args.keys()) == {
        "response_text",
        "cited_hts_codes",
        "cited_shipment_ids",
        "confidence",
    }
