"""Agent orchestrator - the deterministic run pipeline around the LLM loop.

``run_agent`` is the synchronous entry point the API's non-streaming path and the
Phase 4 eval suite call; :func:`src.streaming.stream_agent_run` is the async, SSE-emitting
variant. Both drive the SAME fixed pipeline, factored here into reusable steps so the two
runners share one implementation and persist one identical :class:`~src.models.AgentTrace`:

1. :func:`new_run` - mint the run identity (trace id, timestamp, model, start clock).
2. :func:`run_pre_model_guards` - the two deterministic pre-model guards. Severe
   trade-security signals (contraband / sanctions / seizure / bribery) and cross-vendor
   references short-circuit to an audited trace; the model never runs.
3. **Vendor resolution** - an unknown ``vendor_id`` is a hard reject (404 on the sync path,
   a terminal ``error`` event on the stream). The only step that rejects a well-formed run.
4. :func:`build_agent` - a fresh tool-calling agent (Claude on Vertex, extended thinking
   enabled) bound to the :class:`~src.tools.vendor_context.VendorContext` schema. Built per
   run - chat models carry per-invocation tool bindings and must not be memoized.
5. **Invoke** - the runner drives the agent inside a
   :func:`~src.tracing.trace_context.trace_context` so every tool call appends to one
   ambient trace. ``run_agent`` invokes synchronously; ``stream_agent_run`` drives the same
   graph via ``astream_events`` and maps each tool's start/stop to a stage event. The trace
   ``ContextVar`` (and the vendor runtime context) propagate into the tools whether they run
   inline (sync) or on a worker thread (async driver).
6. :func:`build_run_trace` - recover the classification and draft from the recorded tool
   calls; if the loop ended without a grounded draft (it errored, hit the recursion cap, or
   never called ``draft_clearance_response``), substitute a safe fallback draft and mark the
   run ``iteration_cap_exceeded``.
7. :func:`persist_result` - write exactly one :class:`~src.models.AgentTrace`, then project
   it to the lean :class:`AgentResult` the API returns.

The vendor scope is resolved here and bound into the runtime *context*, never into a
model-facing argument - the LLM has no slot to inject or override which vendor it sees.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_google_vertexai.model_garden import ChatAnthropicVertex
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict

from src import repository
from src.config import ANTHROPIC_VERTEX_REGION, GCP_PROJECT, VERTEX_PRIMARY_MODEL
from src.models import (
    AgentTrace,
    ImportClassification,
    InquiryIntent,
    ToolCallLog,
    TraceDisposition,
)
from src.safeguards.cross_vendor_guard import detect_cross_vendor_reference
from src.safeguards.escalation_guard import should_escalate
from src.tools.classify_import_restriction import classify_import_restriction
from src.tools.draft_clearance_response import draft_clearance_response
from src.tools.lookup_shipment_manifest import lookup_shipment_manifest
from src.tools.retrieve_tariff_regulation import retrieve_tariff_regulation
from src.tools.vendor_context import VendorContext
from src.tracing.trace_context import trace_context

_logger = logging.getLogger(__name__)

# Supersteps, not model calls: a tool-calling round is model->tools = 2 supersteps, so the
# normal flow (classify -> lookup -> retrieve -> draft = 4 rounds) is ~9 supersteps.
# 14 leaves headroom for ~2 extra rounds (e.g. a re-retrieve) before the loop is
# capped and the step-6 fallback fires.
RECURSION_LIMIT = 14

_FALLBACK_DRAFT = (
    "The assistant could not complete a grounded clearance response for this inquiry "
    "within its processing limits, so no draft was produced. Please review the inquiry "
    "and handle it manually, or resubmit."
)

_CROSS_VENDOR_REFUSAL_DRAFT = (
    "This inquiry references records outside your authorized vendor scope, so it cannot "
    "be processed. For trade-compliance isolation, information about another vendor's "
    "shipments or records is never disclosed. Please resubmit referencing only your own "
    "vendor and shipments."
)

_SYSTEM_PROMPT = """\
You are a US trade-compliance assistant for a single authorized vendor. \
You help an analyst understand why imports are held or flagged and draft an official clearance \
response for that analyst — a human — to review and send. You never send anything yourself.

You can only see the current vendor's data. You cannot choose or change which vendor that is.

TOOLS — call them in this order:
1. classify_import_restriction — ALWAYS call this first, exactly once, to classify the inquiry.
2. lookup_shipment_manifest — call this whenever the inquiry references a shipment or specific \
goods, to fetch the current vendor's shipments and their declared manifest lines.
3. retrieve_tariff_regulation — call this with a precise query derived from the classification and \
any looked-up HTS codes, to pull the relevant Harmonized Tariff Schedule (HTS) clauses.
4. draft_clearance_response — call this EXACTLY ONCE, at the very end. Your task is complete once \
you have called it; do not call any tool afterward.

GROUNDING DISCIPLINE — this is the load-bearing part:
- After each tool call, restate what it ACTUALLY returned (counts, shipment_ids, hts_codes, \
restriction bands) and choose your next action from those concrete values, not from assumptions.
- Every factual claim in your draft MUST be grounded in a looked-up shipment or a retrieved HTS \
clause. Cite shipments by their shipment_id and regulations by their hts_code.
- HTS clauses describe regulations IN GENERAL. A clause is never evidence that a specific shipment \
has any property. Do not pivot from "the rule says X" to "your shipment is X" without a shipment \
lookup result that backs it.
- If the lookup returned ZERO shipments, the draft MUST open by stating that no matching shipments \
were found, and MUST NOT reference any hold, flag, restriction, or outcome for a specific shipment.
- Never invent shipment ids, dates, declared values, HTS codes, or flag reasons. Make no legal or \
customs determination beyond what the retrieved clause text states.

Before you call draft_clearance_response, run this checklist:
- Was the lookup empty? Then say so and make no specific-shipment claims.
- Is every shipment_id you cite present in a lookup result?
- Is every regulatory assertion tied to a retrieved HTS clause?
If any check fails, soften or remove the claim. The draft is for human review — keep it in plain, \
professional English."""


class UnknownVendorError(Exception):
    """Raised when the requested ``vendor_id`` is not in Firestore (API -> 404)."""

    def __init__(self, vendor_id: str) -> None:
        super().__init__(f"Unknown vendor: {vendor_id}")
        self.vendor_id = vendor_id


class AgentResult(BaseModel):
    """The orchestrator's per-run result and the ``POST /api/inquiry`` response body.

    A lean projection of the persisted :class:`~src.models.AgentTrace`: enough for the
    UI to render the outcome immediately, while the full audit record (every tool
    call, token/latency aggregates) is read back from ``GET /api/traces``.
    """

    model_config = ConfigDict(frozen=True)

    trace_id: str
    disposition: TraceDisposition
    draft_response: str | None
    classification: ImportClassification | None
    tool_call_count: int
    tool_names: list[str]
    duration_ms: float
    model: str
    escalation_reason: str | None = None
    # Billable token split (see _TokenUsage / AgentTrace): output_tokens includes
    # thoughts_tokens and prompt + output == total.
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thoughts_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class RunMeta:
    """Per-run identity and timing, threaded through the shared pipeline steps."""

    trace_id: str
    timestamp: str  # ISO-8601 run start
    vendor_id: str
    inquiry: str
    model: str
    started: float  # time.perf_counter() at run start, for the duration metric


def new_run(vendor_id: str, inquiry: str, model_id: str | None) -> RunMeta:
    """Mint a fresh run identity. ``model_id`` overrides the primary model (the eval seam)."""
    return RunMeta(
        trace_id=f"tr-{uuid.uuid4().hex}",
        timestamp=datetime.now(UTC).isoformat(),
        vendor_id=vendor_id,
        inquiry=inquiry,
        model=model_id or VERTEX_PRIMARY_MODEL,
        started=time.perf_counter(),
    )


def _elapsed_ms(meta: RunMeta) -> float:
    """Wall-clock milliseconds since the run started - the trace's latency metric."""
    return (time.perf_counter() - meta.started) * 1000.0


# The SSE ``guard_triggered`` vocabulary, owned here (the lower module) so the streaming
# protocol can reuse it without an import cycle. These are the two deterministic guards.
GuardKind = Literal["escalation", "cross_vendor"]


@dataclass(frozen=True)
class PreModelGuard:
    """A deterministic pre-model short-circuit: the audit trace to persist plus the
    SSE-facing guard signal (``kind`` + ``reason``). The model is never built or called."""

    trace: AgentTrace
    kind: GuardKind
    reason: str | None


def run_pre_model_guards(meta: RunMeta) -> PreModelGuard | None:
    """Run the two deterministic guards (escalation, then cross-vendor) in order.

    Returns the short-circuit trace + signal if either fires, else ``None``. Both build a
    complete :class:`~src.models.AgentTrace` so a guarded run is audited identically to one
    that reached the model - the audit signal a reviewer expects to stay at zero.
    """
    escalation = should_escalate(meta.inquiry)
    if escalation.escalate:
        return PreModelGuard(
            trace=AgentTrace(
                trace_id=meta.trace_id,
                timestamp=meta.timestamp,
                vendor_id=meta.vendor_id,
                user_inquiry=meta.inquiry,
                disposition=TraceDisposition.ESCALATED,
                model=meta.model,
                escalation_reason=escalation.reason,
                duration_ms=_elapsed_ms(meta),
            ),
            kind="escalation",
            reason=escalation.reason,
        )

    cross_vendor = detect_cross_vendor_reference(
        meta.vendor_id, meta.inquiry, repository.get_shipment_owner
    )
    if cross_vendor.is_violation:
        refusal = ImportClassification(
            intent=InquiryIntent.CROSS_VENDOR_REFUSAL,
            confidence=1.0,
            reasoning=cross_vendor.reason or "Cross-vendor reference detected.",
        )
        return PreModelGuard(
            trace=AgentTrace(
                trace_id=meta.trace_id,
                timestamp=meta.timestamp,
                vendor_id=meta.vendor_id,
                user_inquiry=meta.inquiry,
                classification=refusal,
                draft_response=_CROSS_VENDOR_REFUSAL_DRAFT,
                disposition=TraceDisposition.DRAFT,
                model=meta.model,
                duration_ms=_elapsed_ms(meta),
            ),
            kind="cross_vendor",
            reason=cross_vendor.reason,
        )
    return None


def build_agent(model_id: str) -> CompiledStateGraph[Any, VendorContext, Any, Any]:
    """Construct a fresh tool-calling agent bound to the vendor-context schema.

    Built with :func:`langchain.agents.create_agent` (the LangChain 1.0 successor to the
    deprecated ``langgraph.prebuilt.create_react_agent``). The context type-param is pinned
    to :class:`VendorContext` - ``create_agent`` threads it into the compiled graph's return
    type, so the ``context=`` kwarg at the invoke site type-checks with no cast; the
    state/input/output params are langgraph internals we treat opaquely. Isolated so tests
    can substitute a fake agent (or a fake chat model) without a model or credentials.
    """
    # Thinking rides in model_kwargs - the class has no dedicated field for it. Two
    # coupled constraints: budget_tokens must stay below max_output_tokens (thinking
    # bills as output), and extended thinking rejects pinned sampling - temperature
    # stays at the Anthropic default (1.0); grounding lives in the system prompt +
    # tools, not in greedy decoding.
    model = ChatAnthropicVertex(
        project=GCP_PROJECT,
        location=ANTHROPIC_VERTEX_REGION,
        model_name=model_id,
        temperature=1.0,
        max_output_tokens=4096,
        model_kwargs={"thinking": {"type": "enabled", "budget_tokens": 2048}},
    )
    return create_agent(
        model=model,
        tools=[
            classify_import_restriction,
            lookup_shipment_manifest,
            retrieve_tariff_regulation,
            draft_clearance_response,
        ],
        system_prompt=_SYSTEM_PROMPT,
        context_schema=VendorContext,
    )


def _extract_classification(tool_calls: tuple[ToolCallLog, ...]) -> ImportClassification | None:
    """Recover the classifier result from the first classify call's recorded OUTPUT."""
    for call in tool_calls:
        if call.tool_name == "classify_import_restriction":
            try:
                return ImportClassification.model_validate(call.output)
            except Exception:  # noqa: BLE001 - a malformed classify output is non-fatal
                return None
    return None


def _extract_draft(tool_calls: tuple[ToolCallLog, ...]) -> str | None:
    """Recover the draft text from the last draft call's recorded INPUT.

    The draft tool records its ``response_text`` as call *input* (it persists nothing
    itself); the orchestrator is the reader of record. The last call wins if the model
    drafts more than once, though the prompt mandates exactly one.
    """
    draft: str | None = None
    for call in tool_calls:
        if call.tool_name == "draft_clearance_response":
            text = call.input.get("response_text")
            if isinstance(text, str):
                draft = text
    return draft


class _TokenUsage(NamedTuple):
    """The run's billable token split, summed across its AI messages.

    Sourced from each message's standardized ``usage_metadata`` (langchain-core), which
    ``langchain-google-vertexai`` fills from the native Anthropic counts: ``input_tokens``
    <- input + cache_read + cache_creation (Anthropic's raw ``input_tokens`` excludes
    cached tokens; the lib rolls them back in) and ``output_tokens`` <- verbatim.
    Thinking bills at the OUTPUT rate and Anthropic exposes NO reasoning sub-split (no
    ``output_token_details.reasoning``), so ``thoughts_tokens`` reads 0 on this provider
    while the thinking spend stays inside ``output_tokens``; ``prompt + output == total``
    still holds.
    """

    prompt_tokens: int
    output_tokens: int
    thoughts_tokens: int
    total_tokens: int


def _sum_tokens(messages: list[BaseMessage]) -> _TokenUsage | None:
    """Aggregate the billable token split across the run's AI messages.

    ``None`` when no message carried usage (e.g. a faked or usage-less run), which keeps
    the trace's token fields ``None`` rather than a misleading all-zero split.

    The ``messages`` are the agent graph's final ``state["messages"]`` (the streaming
    runner captures the same list from the root ``on_chain_end`` event), so a tool's own
    internal model call - e.g. ``classify_import_restriction``'s structured-output call -
    is excluded from the sum, exactly as on the synchronous path.
    """
    prompt = output = thoughts = total = 0
    found = False
    for message in messages:
        usage = getattr(message, "usage_metadata", None)
        if not usage:
            continue
        found = True
        prompt += int(usage.get("input_tokens", 0))
        output += int(usage.get("output_tokens", 0))
        total += int(usage.get("total_tokens", 0))
        # Stays 0 on Anthropic - no reasoning sub-split is exposed (see _TokenUsage).
        thoughts += int((usage.get("output_token_details") or {}).get("reasoning", 0))
    return _TokenUsage(prompt, output, thoughts, total) if found else None


def build_run_trace(
    meta: RunMeta,
    tool_calls: tuple[ToolCallLog, ...],
    result_messages: list[BaseMessage],
    invoke_error: Exception | None,
) -> AgentTrace:
    """Steps 6-7 (trace assembly): recover the classification + draft from the recorded
    tool calls, apply the no-draft fallback, sum the billable tokens, and assemble the
    single audit trace. Shared by the sync and streaming runners; the caller persists it.
    """
    classification = _extract_classification(tool_calls)
    draft_response = _extract_draft(tool_calls)

    # (6) Fallback when the loop ended without a grounded draft (error, cap, or skipped).
    if draft_response is None:
        reason = (
            f"Agent ended without a draft ({type(invoke_error).__name__}: {invoke_error})."
            if invoke_error is not None
            else "Agent ended without calling draft_clearance_response before its iteration cap."
        )
        classification = ImportClassification(
            intent=InquiryIntent.ITERATION_CAP_EXCEEDED,
            confidence=0.0,
            reasoning=reason,
        )
        draft_response = _FALLBACK_DRAFT

    usage = _sum_tokens(result_messages)
    return AgentTrace(
        trace_id=meta.trace_id,
        timestamp=meta.timestamp,
        vendor_id=meta.vendor_id,
        user_inquiry=meta.inquiry,
        classification=classification,
        tool_calls=tool_calls,
        draft_response=draft_response,
        disposition=TraceDisposition.DRAFT,
        model=meta.model,
        duration_ms=_elapsed_ms(meta),
        prompt_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        thoughts_tokens=usage.thoughts_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
    )


def persist_result(trace: AgentTrace) -> AgentResult:
    """Write the single audit document and project it to the lean API result."""
    repository.put_trace(trace)
    return AgentResult(
        trace_id=trace.trace_id,
        disposition=trace.disposition,
        draft_response=trace.draft_response,
        classification=trace.classification,
        tool_call_count=len(trace.tool_calls),
        tool_names=[call.tool_name for call in trace.tool_calls],
        duration_ms=trace.duration_ms or 0.0,
        model=trace.model,
        escalation_reason=trace.escalation_reason,
        prompt_tokens=trace.prompt_tokens,
        output_tokens=trace.output_tokens,
        thoughts_tokens=trace.thoughts_tokens,
        total_tokens=trace.total_tokens,
    )


def run_agent(vendor_id: str, inquiry: str, model_id: str | None = None) -> AgentResult:
    """Run the pipeline synchronously for one analyst inquiry and persist its audit trace.

    ``vendor_id`` is the deterministically resolved scope (validated against the allowlist
    and dropdown upstream); ``inquiry`` is the analyst's raw question. ``model_id`` overrides
    the primary model - used by the Haiku-vs-Sonnet eval. The async, SSE-emitting variant
    is :func:`src.streaming.stream_agent_run`; both share the steps documented above.
    """
    meta = new_run(vendor_id, inquiry, model_id)

    # (2) Deterministic pre-model guards - severe security / cross-vendor signals never reach
    # the model, but are still audited as one trace.
    guard = run_pre_model_guards(meta)
    if guard is not None:
        return persist_result(guard.trace)

    # (3) Resolve vendor scope - an unknown vendor is a hard reject (the API maps it to 404).
    if repository.get_vendor(vendor_id) is None:
        raise UnknownVendorError(vendor_id)

    # (4-5) Build a fresh agent and invoke it synchronously inside the ambient trace context.
    # The whole run is synchronous, so the ContextVar is shared across the tool calls without
    # any thread-hop bookkeeping.
    agent = build_agent(meta.model)
    result_messages: list[BaseMessage] = []
    invoke_error: Exception | None = None
    with trace_context(meta.trace_id, vendor_id) as ctx:
        try:
            output = agent.invoke(
                {"messages": [HumanMessage(content=inquiry)]},
                config={"recursion_limit": RECURSION_LIMIT},
                context={"vendor_id": vendor_id},
            )
            result_messages = list(output.get("messages", []))
        except Exception as exc:  # noqa: BLE001 - any loop failure degrades to a fallback draft
            invoke_error = exc
            _logger.exception("agent invocation failed for trace %s", meta.trace_id)

    # (6-7) Assemble the single audit trace (with the no-draft fallback) and persist it.
    trace = build_run_trace(meta, tuple(ctx.tool_calls), result_messages, invoke_error)
    return persist_result(trace)
