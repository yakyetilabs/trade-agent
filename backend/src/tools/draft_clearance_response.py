"""Tool 4: draft_clearance_response (signals only - does not persist).

Per the draft-only commitment, this tool records the analyst-facing draft as a
*signal* on the trace and returns the active trace id. It does **not** write to
Firestore and has no network hook to submit anything to a port or customs
system - the surrounding agent loop persists one atomic trace at the end (so it
can attach run-level metadata the tool can't see), and a human reviews and sends
every response.
"""

from langchain_core.tools import tool

from src.tracing.trace_context import get_current_trace, record_tool_call


def run_draft_clearance_response(
    response_text: str,
    cited_hts_codes: list[str],
    cited_shipment_ids: list[str],
    confidence: float,
) -> dict[str, object]:
    """Pure core: record the draft on the trace and return the trace id."""
    tool_input: dict[str, object] = {
        "response_text": response_text,
        "cited_hts_codes": cited_hts_codes,
        "cited_shipment_ids": cited_shipment_ids,
        "confidence": confidence,
    }
    with record_tool_call("draft_clearance_response", tool_input) as out:
        trace = get_current_trace()
        trace_id = trace.trace_id if trace is not None else "no-trace"
        result: dict[str, object] = {"trace_id": trace_id, "status": "drafted"}
        out.update(result)
    return result


@tool
def draft_clearance_response(
    response_text: str,
    cited_hts_codes: list[str],
    cited_shipment_ids: list[str],
    confidence: float,
) -> dict[str, object]:
    """Record your final clearance-response draft for human review. Provide the response text, the
    HTS codes you cite, the shipment IDs you cite, and your confidence (0-1). This does NOT send
    anything - a human reviews and sends every response. Call this exactly once, at the end."""
    return run_draft_clearance_response(
        response_text, cited_hts_codes, cited_shipment_ids, confidence
    )
