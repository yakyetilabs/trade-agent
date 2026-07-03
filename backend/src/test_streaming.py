"""Unit tests for the Layer-1 streaming runner and the SSE event protocol.

Hermetic like ``test_agent.py``: ``build_agent`` is replaced with a fake whose
``astream_events`` yields a scripted event stream and appends tool calls through the same
``record_tool_call`` seam the real tools use - so the runner's stage mapping, summary
projection, token sum, guard short-circuits, fallback, and single-trace persistence are
exercised with no Vertex, Pinecone, Firestore, or credentials. The deterministic guards
run for real. Tests drive the async generator with ``asyncio.run`` (no async plugin).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from typing import cast

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, BaseMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable

from src import agent, repository, streaming
from src.agent import AgentResult
from src.models import (
    AgentTrace,
    GoodsCategory,
    ImportClassification,
    InquiryIntent,
    RestrictionLevel,
    TraceDisposition,
    Vendor,
)
from src.streaming import (
    DoneEvent,
    ErrorEvent,
    GuardTriggeredEvent,
    RunStartedEvent,
    StageCompletedEvent,
    StageStartedEvent,
    StreamEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    _stream_deltas,
    sse_format,
    stream_agent_run,
)
from src.tracing.trace_context import record_tool_call

_VENDOR = Vendor(
    vendor_id="V-001",
    legal_name="Meridian Components LLC",
    country="Taiwan",
    customs_broker="Pacific Rim Customs Brokerage",
    categories=(GoodsCategory.ELECTRONICS,),
)


@dataclass
class _ToolCallSpec:
    """One simulated tool call the fake agent will record + surface as a stage."""

    name: str
    input: dict[str, object]
    output: dict[str, object]


@dataclass
class _ModelStreamSpec:
    """One simulated ``on_chat_model_stream`` chunk: its content plus the langgraph node it
    came from. ``node="model"`` is the agent's own model (surfaced as deltas); any other node
    is a tool-internal model call (e.g. the classifier's structured output) that must NOT
    leak. Content mirrors ``langchain-google-genai``: a plain string or a list of
    ``{"type": "thinking"|"text", ...}`` blocks."""

    content: str | list[str | dict[str, object]]
    node: str = "model"


class _FakeStreamingAgent:
    """Stand-in for the compiled graph under astream_events; records how it was invoked.

    For each scripted tool it emits ``on_tool_start``, runs ``record_tool_call`` (so the
    ToolCallLog is appended before ``on_tool_end`` - the ordering the runner relies on),
    then emits ``on_tool_end``. It closes with the root ``on_chain_end`` (empty parent_ids)
    carrying the final messages. ``nested_messages`` optionally emits a NESTED chain-end
    (a tool-internal model call) the runner must ignore for token summing.
    """

    def __init__(
        self,
        calls: Sequence[_ToolCallSpec] = (),
        messages: Sequence[BaseMessage] = (),
        nested_messages: Sequence[BaseMessage] | None = None,
        error: Exception | None = None,
        model_chunks: Sequence[_ModelStreamSpec] = (),
    ) -> None:
        self._calls = calls
        self._messages = messages
        self._nested_messages = nested_messages
        self._error = error
        self._model_chunks = model_chunks
        self.invoked_with: dict[str, object] | None = None

    async def astream_events(
        self,
        agent_input: dict[str, object],
        config: dict[str, object] | None = None,
        *,
        context: dict[str, object] | None = None,
        version: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        self.invoked_with = {
            "input": agent_input,
            "config": config,
            "context": context,
            "version": version,
        }
        if self._error is not None:
            raise self._error
        # The model's reasoning/answer stream (emitted up front, mirroring the loop reasoning
        # before it calls tools). Each carries langgraph_node metadata so the runner can keep
        # the agent's own model ("model") and drop a tool-internal call (anything else).
        for chunk_spec in self._model_chunks:
            yield {
                "event": "on_chat_model_stream",
                "name": "FakeModel",
                "parent_ids": ["root"],
                "metadata": {"langgraph_node": chunk_spec.node},
                "data": {"chunk": AIMessageChunk(content=chunk_spec.content)},
            }
        for spec in self._calls:
            yield {"event": "on_tool_start", "name": spec.name, "parent_ids": ["root"], "data": {}}
            with record_tool_call(spec.name, spec.input) as out:
                out.update(spec.output)
            yield {"event": "on_tool_end", "name": spec.name, "parent_ids": ["root"], "data": {}}
        if self._nested_messages is not None:
            yield {
                "event": "on_chain_end",
                "name": "inner_model_call",
                "parent_ids": ["root"],  # non-empty: a nested run, not the graph root
                "data": {"output": {"messages": list(self._nested_messages)}},
            }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "parent_ids": [],  # the root graph: its messages are the billable token source
            "data": {"output": {"messages": list(self._messages)}},
        }


# --- Scripted tool calls (mirror the four-stage happy path) ---------------------
def _classify_spec(intent: str = "tariff_lookup", confidence: float = 0.9) -> _ToolCallSpec:
    classification = ImportClassification(
        intent=InquiryIntent(intent),
        confidence=confidence,
        reasoning="duty-rate question about declared goods",
        proposed_hts_heading="8517",
        restriction_band=RestrictionLevel.UNRESTRICTED,
    )
    return _ToolCallSpec(
        name="classify_import_restriction",
        input={"inquiry": "x"},
        output=classification.model_dump(mode="json"),
    )


_LOOKUP_SPEC = _ToolCallSpec(
    name="lookup_shipment_manifest",
    input={"shipment_id": "S-1001"},
    output={"count": 1, "scope_violation": False, "shipment_ids": ["S-1001"]},
)
_RETRIEVE_SPEC = _ToolCallSpec(
    name="retrieve_tariff_regulation",
    input={"query": "smartphones HTS 8517"},
    output={"chunk_count": 3, "exact_hits": 1, "hts_codes": ["8517.13.0000"]},
)


def _draft_spec(text: str) -> _ToolCallSpec:
    return _ToolCallSpec(
        name="draft_clearance_response",
        input={
            "response_text": text,
            "cited_hts_codes": ["8517.13.0000"],
            "cited_shipment_ids": ["S-1001"],
            "confidence": 0.84,
        },
        output={"trace_id": "tr-x", "status": "drafted"},
    )


# --- Monkeypatch seams (patch the names as bound in the streaming module) --------
def _install_agent(monkeypatch: pytest.MonkeyPatch, fake: _FakeStreamingAgent) -> None:
    monkeypatch.setattr(streaming, "build_agent", lambda _model_id: fake)


def _explode_if_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert the model is never built on a pre-model short-circuit path."""

    def _boom(_model_id: str) -> object:
        raise AssertionError("the agent must not be built on this path")

    monkeypatch.setattr(streaming, "build_agent", _boom)


def _capture_traces(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    captured: list[object] = []
    monkeypatch.setattr(repository, "put_trace", captured.append)
    return captured


def _vendor_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "get_vendor", lambda _vid: _VENDOR)


def _stub_owner(monkeypatch: pytest.MonkeyPatch, owner: str | None) -> None:
    monkeypatch.setattr(repository, "get_shipment_owner", lambda _sid: owner)


def _drain(vendor_id: str, inquiry: str, model_id: str | None = None) -> list[StreamEvent]:
    """Run the async streaming generator to completion and collect the emitted events."""

    async def _run() -> list[StreamEvent]:
        return [event async for event in stream_agent_run(vendor_id, inquiry, model_id)]

    return asyncio.run(_run())


def _kinds(events: list[StreamEvent]) -> list[tuple[str, str | None]]:
    """Flatten events to (type-name, stage) tuples for order assertions."""
    out: list[tuple[str, str | None]] = []
    for e in events:
        stage = e.stage if isinstance(e, StageStartedEvent | StageCompletedEvent) else None
        out.append((type(e).__name__, stage))
    return out


# --- Normal grounded run --------------------------------------------------------
def test_normal_run_streams_stage_pairs_then_done(monkeypatch: pytest.MonkeyPatch) -> None:
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)
    fake = _FakeStreamingAgent(
        calls=[
            _classify_spec(),
            _LOOKUP_SPEC,
            _RETRIEVE_SPEC,
            _draft_spec("Shipment S-1001 is held pending an import license per HTS 8517.13.0000."),
        ],
        messages=[
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
            )
        ],
    )
    _install_agent(monkeypatch, fake)

    events = _drain("V-001", "Why is S-1001 held and what license applies?")

    # run_started first, four ordered stage pairs, done last.
    assert _kinds(events) == [
        ("RunStartedEvent", None),
        ("StageStartedEvent", "classify"),
        ("StageCompletedEvent", "classify"),
        ("StageStartedEvent", "lookup"),
        ("StageCompletedEvent", "lookup"),
        ("StageStartedEvent", "retrieve"),
        ("StageCompletedEvent", "retrieve"),
        ("StageStartedEvent", "draft"),
        ("StageCompletedEvent", "draft"),
        ("DoneEvent", None),
    ]

    start = events[0]
    assert isinstance(start, RunStartedEvent)
    assert start.vendor_id == "V-001"
    assert start.trace_id.startswith("tr-")

    # Each stage_completed carries the real, audited summary (live == persisted).
    summaries = {e.stage: e.summary for e in events if isinstance(e, StageCompletedEvent)}
    assert summaries["classify"] == {"intent": "tariff_lookup", "confidence": 0.9}
    assert summaries["lookup"] == {"count": 1, "shipment_ids": ["S-1001"]}
    assert summaries["retrieve"] == {"hts_codes": ["8517.13.0000"], "exact_hit": True}
    assert summaries["draft"] == {"ready": True}

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.result.trace_id == start.trace_id
    assert done.result.disposition is TraceDisposition.DRAFT
    assert done.result.draft_response is not None
    assert done.result.draft_response.startswith("Shipment S-1001 is held")
    assert done.result.tool_call_count == 4
    # Billable token split threaded through the root on_chain_end capture (prompt+output==total).
    assert (done.result.prompt_tokens, done.result.output_tokens, done.result.total_tokens) == (
        100,
        40,
        140,
    )

    # Vendor scope rides in the runtime context (never a model-facing arg); the cap + v2 applied.
    assert fake.invoked_with is not None
    assert fake.invoked_with["context"] == {"vendor_id": "V-001"}
    assert fake.invoked_with["config"] == {"recursion_limit": agent.RECURSION_LIMIT}
    assert fake.invoked_with["version"] == "v2"

    # Exactly one trace persisted, carrying the four tool calls and the same token split.
    assert len(captured) == 1
    trace = captured[0]
    assert isinstance(trace, AgentTrace)
    assert trace.trace_id == start.trace_id
    assert len(trace.tool_calls) == 4
    assert trace.total_tokens == 140


def test_token_split_folds_thoughts_across_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Root-capture feeds _sum_tokens: thoughts fold into output; prompt + output == total."""
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    _capture_traces(monkeypatch)
    fake = _FakeStreamingAgent(
        calls=[_classify_spec(), _draft_spec("Grounded draft citing HTS 8517.13.0000.")],
        messages=[
            AIMessage(
                content="",
                usage_metadata={
                    "input_tokens": 200,
                    "output_tokens": 90,  # 60 visible + 30 thinking
                    "total_tokens": 290,
                    "output_token_details": {"reasoning": 30},
                },
            ),
            AIMessage(
                content="done",
                usage_metadata={
                    "input_tokens": 50,
                    "output_tokens": 20,  # 15 visible + 5 thinking
                    "total_tokens": 70,
                    "output_token_details": {"reasoning": 5},
                },
            ),
        ],
    )
    _install_agent(monkeypatch, fake)

    done = _drain("V-001", "What duty applies to my declared electronics?")[-1]

    assert isinstance(done, DoneEvent)
    assert done.result.prompt_tokens == 250
    assert done.result.output_tokens == 110  # 90 + 20, thoughts already folded in
    assert done.result.thoughts_tokens == 35  # 30 + 5
    assert done.result.total_tokens == 360


def test_only_root_chain_end_counts_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool's internal model call surfaces as a NESTED on_chain_end; only the root counts.

    Mirrors the real classify tool's structured-output call - the runner must key on empty
    parent_ids so the token sum matches the synchronous path's output["messages"] exactly.
    """
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    _capture_traces(monkeypatch)
    fake = _FakeStreamingAgent(
        calls=[_classify_spec(), _draft_spec("Grounded draft.")],
        messages=[
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
            )
        ],
        nested_messages=[
            AIMessage(
                content="inner",
                usage_metadata={"input_tokens": 999, "output_tokens": 999, "total_tokens": 1998},
            )
        ],
    )
    _install_agent(monkeypatch, fake)

    done = _drain("V-001", "What duty applies?")[-1]

    assert isinstance(done, DoneEvent)
    assert done.result.total_tokens == 140  # the decoy nested 1998 is excluded
    assert done.result.prompt_tokens == 100


# --- Model-output deltas (Layer 2: thinking_delta / text_delta) -----------------
def test_stream_deltas_maps_every_content_shape() -> None:
    """The pure chunk-content splitter, over the shapes langchain-google-genai emits."""
    # A plain string chunk is visible answer text.
    assert list(_stream_deltas("hello")) == [("text", "hello")]
    # Empty fragments are dropped (tool-call turns stream empty content).
    assert list(_stream_deltas("")) == []
    # A block list keeps thinking vs text distinct and in order.
    assert list(
        _stream_deltas(
            [
                {"type": "thinking", "thinking": "weigh the manifest"},
                {"type": "text", "text": "here is the answer"},
            ]
        )
    ) == [("thinking", "weigh the manifest"), ("text", "here is the answer")]
    # Empty block fragments are dropped too.
    assert list(_stream_deltas([{"type": "thinking", "thinking": ""}])) == []
    # A bare string element inside a list is visible text.
    assert list(_stream_deltas(["visible"])) == [("text", "visible")]
    # Unknown shapes / block types are ignored, never raised on.
    assert list(_stream_deltas(None)) == []
    assert list(_stream_deltas([{"type": "image", "url": "x"}])) == []


def test_model_stream_maps_deltas_and_excludes_tool_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent-model chunks become thinking/text deltas; a tool-internal model call
    (langgraph_node != "model") is excluded, so its structured-output JSON never leaks."""
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    _capture_traces(monkeypatch)
    fake = _FakeStreamingAgent(
        calls=[_classify_spec(), _draft_spec("Grounded draft.")],
        model_chunks=[
            _ModelStreamSpec([{"type": "thinking", "thinking": "Reviewing "}]),
            _ModelStreamSpec([{"type": "thinking", "thinking": "the manifest."}]),
            _ModelStreamSpec(""),  # a tool-call turn: empty text, no delta
            _ModelStreamSpec([{"type": "text", "text": "All set."}]),
            _ModelStreamSpec('{"intent":"tariff_lookup"}', node="tools"),  # excluded
            _ModelStreamSpec("Plain answer."),  # string content -> text delta
        ],
        messages=[
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            )
        ],
    )
    _install_agent(monkeypatch, fake)

    events = _drain("V-001", "Why is my shipment held?")

    thinking = [e.text for e in events if isinstance(e, ThinkingDeltaEvent)]
    text = [e.text for e in events if isinstance(e, TextDeltaEvent)]
    assert thinking == ["Reviewing ", "the manifest."]
    assert text == ["All set.", "Plain answer."]
    # The tool-node structured-output JSON was dropped, not surfaced as a text delta.
    assert all("intent" not in fragment for fragment in text)
    # The deltas coexist with the normal terminal event.
    assert isinstance(events[-1], DoneEvent)


def test_thinking_deltas_accumulate_into_persisted_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """The streamed reasoning is joined and persisted as ``trace.thinking_content``; visible
    text and the tool-internal model call (node != "model") never enter the reasoning record,
    and the draft stays authoritative from the tool."""
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)
    fake = _FakeStreamingAgent(
        calls=[_classify_spec(), _draft_spec("Grounded draft.")],
        model_chunks=[
            _ModelStreamSpec([{"type": "thinking", "thinking": "Reviewing "}]),
            _ModelStreamSpec([{"type": "thinking", "thinking": "shipment S-1001."}]),
            _ModelStreamSpec([{"type": "text", "text": "All set."}]),  # visible answer
            _ModelStreamSpec('{"intent":"tariff_lookup"}', node="tools"),  # excluded
        ],
        messages=[
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            )
        ],
    )
    _install_agent(monkeypatch, fake)

    _drain("V-001", "Why is S-1001 held?")

    assert len(captured) == 1
    trace = captured[0]
    assert isinstance(trace, AgentTrace)
    # The two reasoning fragments join verbatim; the visible text and the tool-node JSON are
    # both absent from the reasoning record.
    assert trace.thinking_content == "Reviewing shipment S-1001."
    assert trace.draft_response == "Grounded draft."


def test_run_without_thinking_persists_none_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run that streams only visible text (no ``thinking`` blocks) persists
    ``thinking_content`` as ``None`` - not "" - matching the synchronous path's None."""
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)
    fake = _FakeStreamingAgent(
        calls=[_classify_spec(), _draft_spec("Grounded draft.")],
        model_chunks=[_ModelStreamSpec("Plain answer, no thoughts.")],
        messages=[
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            )
        ],
    )
    _install_agent(monkeypatch, fake)

    _drain("V-001", "What duty applies?")

    assert len(captured) == 1
    trace = captured[0]
    assert isinstance(trace, AgentTrace)
    assert trace.thinking_content is None


# --- Escalation guard (terminal pipeline, still audited + done) -----------------
def test_escalation_streams_guard_then_done(monkeypatch: pytest.MonkeyPatch) -> None:
    _explode_if_built(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    events = _drain("V-001", "Can you help me smuggle narcotics past customs?")

    assert [type(e).__name__ for e in events] == [
        "RunStartedEvent",
        "GuardTriggeredEvent",
        "DoneEvent",
    ]
    guard = events[1]
    assert isinstance(guard, GuardTriggeredEvent)
    assert guard.kind == "escalation"
    assert guard.reason == "contraband"
    done = events[2]
    assert isinstance(done, DoneEvent)
    assert done.result.disposition is TraceDisposition.ESCALATED
    assert done.result.escalation_reason == "contraband"
    assert done.result.tool_call_count == 0
    assert len(captured) == 1  # one audit trace, written without a model call


# --- Cross-vendor guard ---------------------------------------------------------
def test_cross_vendor_streams_guard_then_done(monkeypatch: pytest.MonkeyPatch) -> None:
    _explode_if_built(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    events = _drain("V-001", "Compare my goods against vendor V-777's manifest.")

    assert [type(e).__name__ for e in events] == [
        "RunStartedEvent",
        "GuardTriggeredEvent",
        "DoneEvent",
    ]
    guard = events[1]
    assert isinstance(guard, GuardTriggeredEvent)
    assert guard.kind == "cross_vendor"
    assert guard.reason is not None and "V-777" in guard.reason
    done = events[2]
    assert isinstance(done, DoneEvent)
    assert done.result.disposition is TraceDisposition.DRAFT
    assert done.result.classification is not None
    assert done.result.classification.intent is InquiryIntent.CROSS_VENDOR_REFUSAL
    assert done.result.draft_response == agent._CROSS_VENDOR_REFUSAL_DRAFT
    assert len(captured) == 1


# --- Unknown vendor: terminal error, no trace -----------------------------------
def test_unknown_vendor_streams_error_and_writes_no_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _explode_if_built(monkeypatch)  # must not build the model for an unresolved vendor
    _stub_owner(monkeypatch, None)
    monkeypatch.setattr(repository, "get_vendor", lambda _vid: None)
    captured = _capture_traces(monkeypatch)

    events = _drain("V-404", "What is the duty rate for smartphones?")

    assert [type(e).__name__ for e in events] == ["RunStartedEvent", "ErrorEvent"]
    error = events[1]
    assert isinstance(error, ErrorEvent)
    assert "V-404" in error.message
    assert captured == []  # rejected before any persistence, like the sync 404 path


# --- Invoke failure degrades to a fallback draft, still one trace ---------------
def test_stream_failure_degrades_to_fallback_done(monkeypatch: pytest.MonkeyPatch) -> None:
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)
    _install_agent(monkeypatch, _FakeStreamingAgent(error=RuntimeError("vertex stream blew up")))

    events = _drain("V-001", "What is the duty rate for cotton t-shirts?")

    assert isinstance(events[0], RunStartedEvent)
    assert not any(isinstance(e, StageStartedEvent | StageCompletedEvent) for e in events)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.result.draft_response == agent._FALLBACK_DRAFT
    assert done.result.classification is not None
    assert done.result.classification.intent is InquiryIntent.ITERATION_CAP_EXCEEDED
    assert "RuntimeError" in done.result.classification.reasoning
    assert done.result.tool_call_count == 0
    assert len(captured) == 1  # a failed run still produces exactly one audit trace


# --- Real-graph smoke test (the streaming API + ContextVar boundary) ------------
def test_real_graph_streams_through_astream_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive stream_agent_run through the REAL create_agent graph and REAL astream_events.

    Only the chat model is faked (no Vertex/creds), and the tool exercised is
    draft_clearance_response - the one real tool with no external deps, which records through
    record_tool_call and reads the trace via get_current_trace(). This locks in what the
    hermetic tests stub: a real tool span becomes a stage pair, the trace ContextVar and the
    vendor runtime context propagate into the real ToolNode under the async driver, and the
    root on_chain_end capture feeds the token sum. It is the regression guard for the
    astream_events behavior the design depends on (verified at build time).
    """
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    class _BindableFake(FakeMessagesListChatModel):
        """Replays scripted messages intact (keeps tool_calls); no-op bind_tools for the graph."""

        def bind_tools(
            self, tools: object, **kwargs: object
        ) -> Runnable[LanguageModelInput, AIMessage]:
            # The fake only ever replays scripted AIMessages, so binding is a no-op; the cast
            # matches BaseChatModel.bind_tools' AIMessage-output contract (self is BaseMessage-out).
            return cast("Runnable[LanguageModelInput, AIMessage]", self)

    draft_turn = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "draft_clearance_response",
                "args": {
                    "response_text": "Grounded draft citing HTS 8517.13.0000.",
                    "cited_hts_codes": ["8517.13.0000"],
                    "cited_shipment_ids": ["S-1001"],
                    "confidence": 0.8,
                },
                "id": "d1",
            }
        ],
        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
    )
    final_turn = AIMessage(
        content="Done.",
        usage_metadata={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
    )
    fake_model = _BindableFake(responses=[draft_turn, final_turn])
    # build_agent is the REAL one (not patched); only the provider seam is swapped. It passes
    # stream_thoughts=True, so the fake seam must accept the keyword.
    monkeypatch.setattr(agent, "build_chat_model", lambda _model_id, **_kwargs: fake_model)

    events = _drain("V-001", "Draft a clearance response for S-1001.")

    kinds = _kinds(events)
    assert ("StageStartedEvent", "draft") in kinds
    assert ("StageCompletedEvent", "draft") in kinds
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.result.draft_response == "Grounded draft citing HTS 8517.13.0000."
    assert done.result.tool_names == ["draft_clearance_response"]
    # Token sum came from the REAL root on_chain_end capture across both model turns.
    assert done.result.prompt_tokens == 160  # 120 + 40
    assert done.result.output_tokens == 40  # 30 + 10
    assert done.result.total_tokens == 200  # 150 + 50
    # One real trace, recorded through the real record_tool_call under the async driver.
    assert len(captured) == 1
    trace = captured[0]
    assert isinstance(trace, AgentTrace)
    assert [c.tool_name for c in trace.tool_calls] == ["draft_clearance_response"]


class _StreamingTurnsModel(BaseChatModel):
    """A real streaming chat model: each invocation streams one scripted turn's chunks.

    Implements ``_stream`` so ``astream_events`` emits genuine ``on_chat_model_stream``
    events under create_agent's model node - the real-graph proof that the loop's reasoning
    and answer chunks surface as ``thinking_delta`` / ``text_delta``. The hermetic tests
    script the ``langgraph_node`` metadata; this locks that create_agent actually tags its
    own model call ``"model"`` (verified against the live graph at build time).
    """

    turns: list[list[AIMessageChunk]]
    cursor: int = 0

    @property
    def _llm_type(self) -> str:
        return "streaming-turns-fake"

    def _next_turn(self) -> list[AIMessageChunk]:
        turn = self.turns[self.cursor]
        self.cursor += 1
        return turn

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> Iterator[ChatGenerationChunk]:
        for chunk in self._next_turn():
            yield ChatGenerationChunk(message=chunk)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        # astream_events uses _stream; _generate satisfies the ABC by merging the same chunks.
        turn = self._next_turn()
        merged: BaseMessageChunk = turn[0]
        for chunk in turn[1:]:
            merged = merged + chunk
        return ChatResult(generations=[ChatGeneration(message=merged)])

    def bind_tools(
        self, tools: object, **kwargs: object
    ) -> Runnable[LanguageModelInput, AIMessage]:
        # Tool calls are scripted directly onto the chunks, so binding is a no-op; the cast
        # matches BaseChatModel.bind_tools' AIMessage-output contract.
        return cast("Runnable[LanguageModelInput, AIMessage]", self)


def test_real_graph_streams_thinking_and_text_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive stream_agent_run through the REAL create_agent graph with a streaming model.

    Locks the assumption the hermetic tests script rather than prove: create_agent tags its
    own model call ``langgraph_node == "model"``, so the loop's thinking + answer chunks
    actually surface as ``thinking_delta`` / ``text_delta``. Only the chat model is faked (a
    real ``_stream``); the tool exercised is the dependency-free draft tool. The draft still
    rides the tool + ``done`` result - it is never reassembled from the text deltas.
    """
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    reason_chunk = AIMessageChunk(
        content=[{"type": "thinking", "thinking": "Reviewing shipment S-1001."}]
    )
    call_chunk = AIMessageChunk(
        content="",
        tool_calls=[
            {
                "name": "draft_clearance_response",
                "args": {
                    "response_text": "Grounded draft citing HTS 8517.13.0000.",
                    "cited_hts_codes": ["8517.13.0000"],
                    "cited_shipment_ids": ["S-1001"],
                    "confidence": 0.8,
                },
                "id": "d1",
            }
        ],
    )
    answer_chunk = AIMessageChunk(content="Draft ready for your review.")
    fake_model = _StreamingTurnsModel(turns=[[reason_chunk, call_chunk], [answer_chunk]])
    monkeypatch.setattr(agent, "build_chat_model", lambda _model_id, **_kwargs: fake_model)

    events = _drain("V-001", "Draft a clearance response for S-1001.")

    thinking = "".join(e.text for e in events if isinstance(e, ThinkingDeltaEvent))
    text = "".join(e.text for e in events if isinstance(e, TextDeltaEvent))
    assert "Reviewing shipment S-1001." in thinking
    assert "Draft ready for your review." in text
    # A real draft-stage pair still animates, and the authoritative draft rides the tool.
    assert ("StageCompletedEvent", "draft") in _kinds(events)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.result.draft_response == "Grounded draft citing HTS 8517.13.0000."
    assert done.result.tool_names == ["draft_clearance_response"]
    # The reasoning is accumulated through the REAL graph and persisted on the single trace.
    assert len(captured) == 1
    persisted = captured[0]
    assert isinstance(persisted, AgentTrace)
    assert persisted.thinking_content is not None
    assert "Reviewing shipment S-1001." in persisted.thinking_content


# --- SSE serialization (the wire protocol) --------------------------------------
def _minimal_result() -> AgentResult:
    return AgentResult(
        trace_id="tr-abc",
        disposition=TraceDisposition.DRAFT,
        draft_response="draft text",
        classification=None,
        tool_call_count=0,
        tool_names=[],
        duration_ms=12.5,
        model="gemini-2.5-flash",
    )


def test_event_names_match_the_contract() -> None:
    assert RunStartedEvent.event_name == "run_started"
    assert StageStartedEvent.event_name == "stage_started"
    assert StageCompletedEvent.event_name == "stage_completed"
    assert ThinkingDeltaEvent.event_name == "thinking_delta"
    assert TextDeltaEvent.event_name == "text_delta"
    assert GuardTriggeredEvent.event_name == "guard_triggered"
    assert DoneEvent.event_name == "done"
    assert ErrorEvent.event_name == "error"


def test_sse_format_thinking_and_text_deltas() -> None:
    thinking_block = sse_format(ThinkingDeltaEvent(text="weighing the manifest"))
    assert thinking_block.startswith("event: thinking_delta\n")
    assert thinking_block.endswith("\n\n")
    thinking_line = next(line for line in thinking_block.splitlines() if line.startswith("data: "))
    assert json.loads(thinking_line.removeprefix("data: ")) == {"text": "weighing the manifest"}

    text_block = sse_format(TextDeltaEvent(text="Draft ready."))
    assert text_block.startswith("event: text_delta\n")
    text_line = next(line for line in text_block.splitlines() if line.startswith("data: "))
    assert json.loads(text_line.removeprefix("data: ")) == {"text": "Draft ready."}


def test_sse_format_emits_event_line_and_pure_data_payload() -> None:
    event = RunStartedEvent(trace_id="tr-1", vendor_id="V-001", model="gemini-2.5-flash")
    block = sse_format(event)
    assert block.startswith("event: run_started\n")
    assert block.endswith("\n\n")
    data_line = next(line for line in block.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    # The class-level event name rides the event: line only, not the JSON data payload.
    assert payload == {"trace_id": "tr-1", "vendor_id": "V-001", "model": "gemini-2.5-flash"}
    assert "event_name" not in payload


def test_sse_format_done_nests_the_full_result() -> None:
    block = sse_format(DoneEvent(result=_minimal_result()))
    assert block.startswith("event: done\n")
    payload = json.loads(next(line for line in block.splitlines() if line.startswith("data: "))[6:])
    assert payload["result"]["trace_id"] == "tr-abc"
    assert payload["result"]["disposition"] == "draft"
