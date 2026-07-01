"""Layer-1 Server-Sent Events: the streaming protocol + the async agent runner.

This is the streaming half of the agent surface. :func:`stream_agent_run` is the async,
progress-emitting sibling of :func:`src.agent.run_agent`: it drives the SAME pipeline (the
steps documented in ``src/agent.py``) but via ``astream_events``, so each tool's start and
stop becomes a pipeline-stage event the console animates. It persists the SAME single
:class:`~src.models.AgentTrace` and ends with a ``done`` event carrying the ``AgentResult``.

Why Layer 1 only (progress, not token-by-token draft text) and the full event contract:
see ``docs/FRONTEND_PLAN.md``. The event vocabulary here is that contract:

- ``run_started``    ``{ trace_id, vendor_id, model }`` - always first.
- ``stage_started``  ``{ stage }`` - a tool began (classify / lookup / retrieve / draft).
- ``stage_completed````{ stage, summary }`` - a tool finished; ``summary`` is the SAME
  compact projection recorded on the audit trace, so the live view never diverges from it.
- ``guard_triggered````{ kind, reason }`` - a deterministic pre-model guard fired; the model
  never ran. Terminal for the pipeline, still followed by ``done`` (the guard is audited too).
- ``done``           ``{ result }`` - the full :class:`~src.agent.AgentResult`; closes the run.
- ``error``          ``{ message }`` - an unknown vendor or an unexpected failure; terminal.

Transport (verified at build time against langchain-core 1.4): the trace ``ContextVar`` and
the vendor runtime context both propagate into the synchronous tools when the graph runs
under the async driver, and two concurrent runs stay isolated (each request is its own task
context), so holding the trace context across ``yield`` points is safe.
"""

import logging
from collections.abc import AsyncIterator, Sequence
from typing import ClassVar, Literal

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ConfigDict

from src import repository
from src.agent import (
    RECURSION_LIMIT,
    AgentResult,
    GuardKind,
    build_agent,
    build_run_trace,
    new_run,
    persist_result,
    run_pre_model_guards,
)
from src.models import ToolCallLog
from src.tracing.trace_context import trace_context

_logger = logging.getLogger(__name__)

# The four pipeline stages the console animates, and the locked four-tool contract
# (CLAUDE.md) mapped onto them. The keys are the ``@tool`` function names in ``src/tools/``.
Stage = Literal["classify", "lookup", "retrieve", "draft"]

TOOL_TO_STAGE: dict[str, Stage] = {
    "classify_import_restriction": "classify",
    "lookup_shipment_manifest": "lookup",
    "retrieve_tariff_regulation": "retrieve",
    "draft_clearance_response": "draft",
}


# --- SSE event models: the model's fields are the JSON ``data:`` payload; the class-level
# ``event_name`` is the SSE ``event:`` line (kept off the payload to match the contract shape).


class _StreamEvent(BaseModel):
    """Base for a Layer-1 SSE event. Frozen - an event is an emitted fact, not mutable state."""

    model_config = ConfigDict(frozen=True)
    event_name: ClassVar[str]


class RunStartedEvent(_StreamEvent):
    """The run has a trace id and a resolved scope; the pipeline is about to begin."""

    event_name: ClassVar[str] = "run_started"
    trace_id: str
    vendor_id: str
    model: str


class StageStartedEvent(_StreamEvent):
    """A pipeline stage's tool began executing."""

    event_name: ClassVar[str] = "stage_started"
    stage: Stage


class StageCompletedEvent(_StreamEvent):
    """A pipeline stage finished; ``summary`` carries its real result (the audited projection)."""

    event_name: ClassVar[str] = "stage_completed"
    stage: Stage
    summary: dict[str, object]


class GuardTriggeredEvent(_StreamEvent):
    """A deterministic pre-model guard fired - the model never ran. Followed by ``done``."""

    event_name: ClassVar[str] = "guard_triggered"
    kind: GuardKind
    reason: str | None


class DoneEvent(_StreamEvent):
    """Terminal success: the full run result. Present on every non-error path, guards included."""

    event_name: ClassVar[str] = "done"
    result: AgentResult


class ErrorEvent(_StreamEvent):
    """Terminal failure: an unknown vendor or an unexpected error while processing."""

    event_name: ClassVar[str] = "error"
    message: str


StreamEvent = (
    RunStartedEvent
    | StageStartedEvent
    | StageCompletedEvent
    | GuardTriggeredEvent
    | DoneEvent
    | ErrorEvent
)


def sse_format(event: StreamEvent) -> str:
    """Render one event as an SSE block: an ``event:`` name line + a ``data:`` JSON line."""
    return f"event: {event.event_name}\ndata: {event.model_dump_json()}\n\n"


def _last_log_for(tool_name: str, tool_calls: Sequence[ToolCallLog]) -> ToolCallLog | None:
    """The most recent recorded call for ``tool_name`` - the one whose ``on_tool_end`` just
    fired (``record_tool_call`` appends before the tool returns, verified at build time). The
    system prompt drives strictly sequential single tool calls, so this is unambiguous."""
    for call in reversed(tool_calls):
        if call.tool_name == tool_name:
            return call
    return None


def _stage_summary(tool_name: str, output: dict[str, object]) -> dict[str, object]:
    """Project a tool's recorded trace output to the compact ``stage_completed`` summary.

    Reads the SAME dict that ``record_tool_call`` persisted on the trace, so the live stage
    summary and the audit trail never diverge. Uses ``.get`` throughout - a degraded tool
    output yields an empty-ish summary rather than raising mid-stream.
    """
    if tool_name == "classify_import_restriction":
        return {"intent": output.get("intent"), "confidence": output.get("confidence")}
    if tool_name == "lookup_shipment_manifest":
        return {"count": output.get("count"), "shipment_ids": output.get("shipment_ids", [])}
    if tool_name == "retrieve_tariff_regulation":
        return {
            "hts_codes": output.get("hts_codes", []),
            "exact_hit": bool(output.get("exact_hits", 0)),
        }
    if tool_name == "draft_clearance_response":
        return {"ready": output.get("status") == "drafted"}
    return {}


async def stream_agent_run(
    vendor_id: str, inquiry: str, model_id: str | None = None
) -> AsyncIterator[StreamEvent]:
    """Run the pipeline for one inquiry, emitting Layer-1 progress events as it goes.

    The async, SSE-emitting sibling of :func:`src.agent.run_agent`: same guards, same vendor
    scoping, same single persisted :class:`~src.models.AgentTrace`. It always begins with
    ``run_started`` and ends with exactly one terminal event (``done`` or ``error``); a guard
    short-circuit emits ``guard_triggered`` then ``done``. ``vendor_id`` is the resolved scope
    (checked upstream by the endpoint); ``model_id`` overrides the primary model.
    """
    meta = new_run(vendor_id, inquiry, model_id)
    yield RunStartedEvent(trace_id=meta.trace_id, vendor_id=vendor_id, model=meta.model)

    try:
        # (2) Deterministic pre-model guards: terminal for the pipeline (no model), but still
        # audited as one trace and closed with `done` so the client always ends on done/error.
        guard = run_pre_model_guards(meta)
        if guard is not None:
            result = persist_result(guard.trace)
            yield GuardTriggeredEvent(kind=guard.kind, reason=guard.reason)
            yield DoneEvent(result=result)
            return

        # (3) Vendor resolution. Once the stream is open the HTTP status is 200, so an unknown
        # vendor cannot be a 404 - it surfaces as a terminal error event. The picker only
        # offers resolvable vendors, so this is an edge guard, not the normal path.
        if repository.get_vendor(vendor_id) is None:
            yield ErrorEvent(message=f"Unknown vendor: {vendor_id}")
            return

        # (4-5) Build the agent and drive it via astream_events, mapping each tool's start/stop
        # to a stage event. Tools run synchronously on a worker thread; the trace ContextVar and
        # the vendor runtime context propagate into them (verified at build time).
        agent = build_agent(meta.model)
        result_messages: list[BaseMessage] = []
        invoke_error: Exception | None = None
        with trace_context(meta.trace_id, vendor_id) as ctx:
            try:
                async for event in agent.astream_events(
                    {"messages": [HumanMessage(content=inquiry)]},
                    config={"recursion_limit": RECURSION_LIMIT},
                    context={"vendor_id": vendor_id},
                    version="v2",
                ):
                    kind = event.get("event")
                    # The root graph's final state carries the agent-loop messages, which the
                    # token sum needs (and which exclude any tool-internal model call). The root
                    # is the only chain event with no parent - name-independent identification.
                    if kind == "on_chain_end" and not event.get("parent_ids"):
                        data = event.get("data")
                        output = data.get("output") if isinstance(data, dict) else None
                        if isinstance(output, dict) and "messages" in output:
                            result_messages = list(output["messages"])
                        continue
                    if kind not in ("on_tool_start", "on_tool_end"):
                        continue
                    name = event.get("name")
                    if not isinstance(name, str):
                        continue
                    stage = TOOL_TO_STAGE.get(name)
                    if stage is None:
                        continue
                    if kind == "on_tool_start":
                        yield StageStartedEvent(stage=stage)
                    else:  # on_tool_end - its ToolCallLog is already recorded (append-before-end)
                        log = _last_log_for(name, ctx.tool_calls)
                        summary = _stage_summary(name, log.output) if log is not None else {}
                        yield StageCompletedEvent(stage=stage, summary=summary)
            except Exception as exc:  # noqa: BLE001 - any loop failure degrades to a fallback draft
                invoke_error = exc
                _logger.exception("agent stream failed for trace %s", meta.trace_id)
            tool_calls = tuple(ctx.tool_calls)

        # (6-7) Assemble + persist the single trace (with the no-draft fallback), then close.
        trace = build_run_trace(meta, tool_calls, result_messages, invoke_error)
        yield DoneEvent(result=persist_result(trace))
    except Exception:  # noqa: BLE001 - last resort: never leak an uncaught error mid-stream
        _logger.exception("stream_agent_run failed for trace %s", meta.trace_id)
        yield ErrorEvent(message="Internal error while processing the inquiry.")
