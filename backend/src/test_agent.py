"""Unit tests for the run_agent orchestrator.

Hermetic by construction: the model is never built or called. ``build_agent`` is
replaced with a fake whose ``invoke`` appends tool calls to the ambient trace via the
same ``record_tool_call`` seam the real tools use, so the orchestrator's extraction,
fallback, and trace-persistence logic is exercised exactly as it would be live - with
no Vertex, Pinecone, Firestore, or credentials in the loop.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src import agent, repository
from src.models import (
    AgentTrace,
    GoodsCategory,
    ImportClassification,
    InquiryIntent,
    RestrictionLevel,
    TraceDisposition,
    Vendor,
)
from src.tools.vendor_context import VendorContext
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
    """One simulated tool call the fake agent will append to the trace."""

    name: str
    input: dict[str, object]
    output: dict[str, object]


class _FakeAgent:
    """Stand-in for the compiled ReAct graph; records how it was invoked."""

    def __init__(
        self,
        calls: Sequence[_ToolCallSpec] = (),
        messages: Sequence[BaseMessage] = (),
        error: Exception | None = None,
    ) -> None:
        self._calls = calls
        self._messages = messages
        self._error = error
        self.invoked_with: dict[str, object] | None = None

    def invoke(
        self,
        agent_input: dict[str, object],
        config: dict[str, object] | None = None,
        *,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.invoked_with = {"input": agent_input, "config": config, "context": context}
        if self._error is not None:
            raise self._error
        for spec in self._calls:
            with record_tool_call(spec.name, spec.input) as out:
                out.update(spec.output)
        return {"messages": list(self._messages)}


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


def _install_agent(monkeypatch: pytest.MonkeyPatch, fake: _FakeAgent) -> None:
    monkeypatch.setattr(agent, "build_agent", lambda _model_id: fake)


def _explode_if_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert the model is never built on a pre-model short-circuit path."""

    def _boom(_model_id: str) -> object:
        raise AssertionError("the agent must not be built on this path")

    monkeypatch.setattr(agent, "build_agent", _boom)


def _capture_traces(monkeypatch: pytest.MonkeyPatch) -> list[AgentTrace]:
    captured: list[AgentTrace] = []
    monkeypatch.setattr(repository, "put_trace", captured.append)
    return captured


def _vendor_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "get_vendor", lambda _vid: _VENDOR)


def _stub_owner(monkeypatch: pytest.MonkeyPatch, owner: str | None) -> None:
    monkeypatch.setattr(repository, "get_shipment_owner", lambda _sid: owner)


# --- (1) Escalation guard -------------------------------------------------------
def test_escalation_short_circuits_before_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _explode_if_built(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    result = agent.run_agent("V-001", "Can you help me smuggle narcotics past customs?")

    assert result.disposition is TraceDisposition.ESCALATED
    assert result.escalation_reason == "contraband"
    assert result.classification is None
    assert result.draft_response is None
    assert result.draft_actionable is False
    assert result.tool_call_count == 0
    assert len(captured) == 1  # exactly one audit trace, written without a model call


# --- (2) Cross-vendor guard -----------------------------------------------------
def test_cross_vendor_vendor_reference_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _explode_if_built(monkeypatch)
    _stub_owner(monkeypatch, None)
    _capture_traces(monkeypatch)

    result = agent.run_agent("V-001", "Compare my goods against vendor V-777's manifest.")

    assert result.disposition is TraceDisposition.DRAFT
    assert result.classification is not None
    assert result.classification.intent is InquiryIntent.CROSS_VENDOR_REFUSAL
    assert result.draft_response == agent._CROSS_VENDOR_REFUSAL_DRAFT
    # A refusal carries draft text and DRAFT disposition, but is not releasable.
    assert result.draft_actionable is False
    assert result.tool_call_count == 0


def test_cross_vendor_foreign_shipment_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _explode_if_built(monkeypatch)
    _stub_owner(monkeypatch, "V-002")  # S-9001 is owned by another vendor
    _capture_traces(monkeypatch)

    result = agent.run_agent("V-001", "Why is shipment S-9001 being held at the port?")

    assert result.disposition is TraceDisposition.DRAFT
    assert result.classification is not None
    assert result.classification.intent is InquiryIntent.CROSS_VENDOR_REFUSAL
    assert "S-9001" in (result.classification.reasoning or "")


# --- (3) Vendor resolution ------------------------------------------------------
def test_unknown_vendor_raises_and_writes_no_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    _explode_if_built(monkeypatch)
    _stub_owner(monkeypatch, None)
    monkeypatch.setattr(repository, "get_vendor", lambda _vid: None)
    captured = _capture_traces(monkeypatch)

    with pytest.raises(agent.UnknownVendorError):
        agent.run_agent("V-404", "What is the duty rate for smartphones?")

    assert captured == []  # rejected before any persistence


# --- (5/7) Normal grounded run --------------------------------------------------
def test_normal_run_extracts_classification_draft_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    fake = _FakeAgent(
        calls=[
            _classify_spec(),
            _ToolCallSpec(
                name="lookup_shipment_manifest",
                input={"shipment_id": "S-1001"},
                output={"count": 1, "scope_violation": False, "shipment_ids": ["S-1001"]},
            ),
            _ToolCallSpec(
                name="retrieve_tariff_regulation",
                input={"query": "smartphones HTS 8517"},
                output={"chunk_count": 3, "hts_codes": ["8517.13.0000"]},
            ),
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

    result = agent.run_agent("V-001", "Why is S-1001 held and what license applies?")

    assert result.disposition is TraceDisposition.DRAFT
    assert result.classification is not None
    assert result.classification.intent is InquiryIntent.TARIFF_LOOKUP
    assert result.draft_response is not None
    assert result.draft_response.startswith("Shipment S-1001 is held")
    # A grounded draft tied to a found shipment is releasable - Approve is offered.
    assert result.draft_actionable is True
    assert result.tool_call_count == 4
    # Billable token split surfaced on the result (cost axis). No reasoning detail on
    # this message, so thoughts is 0; prompt + output == total.
    assert result.prompt_tokens == 100
    assert result.output_tokens == 40
    assert result.thoughts_tokens == 0
    assert result.total_tokens == 140
    assert result.tool_names == [
        "classify_import_restriction",
        "lookup_shipment_manifest",
        "retrieve_tariff_regulation",
        "draft_clearance_response",
    ]
    # Vendor scope is bound into runtime context, never a model-facing arg; the cap is applied.
    assert fake.invoked_with is not None
    assert fake.invoked_with["context"] == {"vendor_id": "V-001"}
    assert fake.invoked_with["config"] == {"recursion_limit": agent.RECURSION_LIMIT}
    # Exactly one trace persisted, carrying the embedded tool calls and token split.
    assert len(captured) == 1
    assert len(captured[0].tool_calls) == 4
    assert captured[0].prompt_tokens == 100
    assert captured[0].output_tokens == 40
    assert captured[0].thoughts_tokens == 0
    assert captured[0].total_tokens == 140
    assert captured[0].duration_ms is not None


def test_token_split_folds_thoughts_and_sums_across_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thinking tokens are kept as a sub-split of output, summed over all AI messages.

    On Vertex thinking bills at the OUTPUT rate, so output_tokens already includes the
    reasoning tokens (output_token_details.reasoning) and prompt + output == total. Two
    AI messages (a tool-call turn then the final turn) exercise the per-field summing.
    """
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    fake = _FakeAgent(
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

    result = agent.run_agent("V-001", "What duty applies to my declared electronics?")

    assert result.prompt_tokens == 250
    assert result.output_tokens == 110  # 90 + 20, thoughts already folded in
    assert result.thoughts_tokens == 35  # 30 + 5
    assert result.total_tokens == 360  # 290 + 70 == prompt + output
    assert result.prompt_tokens + result.output_tokens == result.total_tokens
    # A tariff-only run never looks up a shipment, so "no shipment found" does not apply -
    # the informational draft stays releasable.
    assert result.draft_actionable is True
    assert len(captured) == 1
    assert captured[0].thoughts_tokens == 35
    assert captured[0].output_tokens == 110


# --- Actionability: a drafted "no shipments found" note is not releasable ---------
def test_no_matching_shipments_draft_is_not_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lookup that finds nothing yields a drafted "no shipments found" note a human cannot
    Approve & release - there is no shipment to clear. The draft is real (not the fallback)
    and audited, but ``draft_actionable`` is False so the UI hides Approve.
    """
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    fake = _FakeAgent(
        calls=[
            _classify_spec(intent="manifest_flag_resolution"),
            _ToolCallSpec(
                name="lookup_shipment_manifest",
                input={"shipment_id": "S-9999"},
                output={"count": 0, "scope_violation": False, "shipment_ids": []},
            ),
            _ToolCallSpec(
                name="draft_clearance_response",
                input={
                    "response_text": "No shipments matching S-9999 were found for your vendor.",
                    "cited_hts_codes": [],
                    "cited_shipment_ids": [],
                    "confidence": 0.9,
                },
                output={"trace_id": "tr-x", "status": "drafted"},
            ),
        ],
        messages=[AIMessage(content="done")],
    )
    _install_agent(monkeypatch, fake)

    result = agent.run_agent("V-001", "Why is shipment S-9999 held?")

    assert result.disposition is TraceDisposition.DRAFT
    assert result.draft_response is not None
    assert result.draft_response.startswith("No shipments matching S-9999")
    assert result.draft_response != agent._FALLBACK_DRAFT  # a genuine draft, not the fallback
    assert result.draft_actionable is False  # nothing to release -> Approve is gated
    assert result.tool_call_count == 3
    assert len(captured) == 1
    assert captured[0].draft_actionable is False  # persisted on the audit trace too


# --- (6) No-draft fallback ------------------------------------------------------
def test_loop_without_draft_falls_back_to_iteration_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    fake = _FakeAgent(
        calls=[
            _classify_spec(intent="manifest_flag_resolution"),
            _ToolCallSpec(
                name="lookup_shipment_manifest",
                input={"status": "held"},
                output={"count": 0, "scope_violation": False, "shipment_ids": []},
            ),
        ],
        messages=[AIMessage(content="I need more info")],
    )
    _install_agent(monkeypatch, fake)

    result = agent.run_agent("V-001", "What's going on with my held shipments?")

    assert result.disposition is TraceDisposition.DRAFT
    assert result.draft_response == agent._FALLBACK_DRAFT
    assert result.classification is not None
    assert result.classification.intent is InquiryIntent.ITERATION_CAP_EXCEEDED
    assert result.draft_actionable is False  # a no-draft fallback is not releasable
    assert result.tool_call_count == 2  # the partial tool calls are still audited
    assert len(captured) == 1


def test_invoke_failure_degrades_to_fallback_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    fake = _FakeAgent(error=RuntimeError("vertex transport blew up"))
    _install_agent(monkeypatch, fake)

    result = agent.run_agent("V-001", "What is the duty rate for cotton t-shirts?")

    assert result.disposition is TraceDisposition.DRAFT
    assert result.draft_response == agent._FALLBACK_DRAFT
    assert result.classification is not None
    assert result.classification.intent is InquiryIntent.ITERATION_CAP_EXCEEDED
    assert "RuntimeError" in result.classification.reasoning
    assert result.draft_actionable is False  # a degraded fallback is not releasable
    assert result.tool_call_count == 0
    assert len(captured) == 1  # a failed run still produces exactly one audit trace


# --- Build-time wiring (security-critical: vendor context + the four tools) ------
def test_build_agent_binds_vendor_context_and_the_four_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real create_agent graph carries the vendor context schema and the four tools.

    Unlike the orchestrator tests above (which replace ``build_agent`` wholesale), this
    builds the ACTUAL agent graph; only the chat model is swapped for a credential-free
    fake, so no Vertex SDK init or network call happens. It is the security-critical
    wiring check the faked tests cannot make: vendor scope must ride in the runtime
    ``context_schema``, never as a model-facing tool argument the LLM could set or override.
    """
    fake_model = GenericFakeChatModel(messages=iter([AIMessage(content="ok")]))
    # Patch the provider seam so the real build_agent graph is constructed with a
    # credential-free fake chat model (no Vertex SDK init, no network). build_agent passes
    # stream_thoughts=True, so the fake seam must accept the keyword.
    monkeypatch.setattr(agent, "build_chat_model", lambda _model_id, **_kwargs: fake_model)

    compiled = agent.build_agent(agent.VERTEX_PRIMARY_MODEL)

    assert isinstance(compiled, CompiledStateGraph)
    # Vendor scope is bound as runtime context: the load-bearing isolation guarantee.
    assert compiled.context_schema is VendorContext
    # Exactly the four trade tools are wired into the loop, no more and no fewer.
    tools_node = compiled.nodes["tools"].bound
    assert isinstance(tools_node, ToolNode)
    assert set(tools_node.tools_by_name) == {
        "classify_import_restriction",
        "lookup_shipment_manifest",
        "retrieve_tariff_regulation",
        "draft_clearance_response",
    }
