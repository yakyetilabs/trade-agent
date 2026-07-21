"""Unit tests for the run_agent orchestrator.

Hermetic by construction: the model is never built or called. ``build_agent`` is
replaced with a fake whose ``invoke`` appends tool calls to the ambient trace via the
same ``record_tool_call`` seam the real tools use, so the orchestrator's extraction,
fallback, and trace-persistence logic is exercised exactly as it would be live - with
no Vertex, Pinecone, Firestore, or credentials in the loop.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import anthropic
import httpx
import pytest
from google.api_core import exceptions as google_api_exceptions
from google.genai import errors as google_genai_errors
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src import agent, repository
from src.models import (
    AgentTrace,
    GoodsCategory,
    ImportClassification,
    InquiryIntent,
    RestrictionLevel,
    RunErrorClass,
    ToolCallLog,
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
    # Vendor scope and the run's model binding ride in runtime context, never a
    # model-facing arg; the cap is applied.
    assert fake.invoked_with is not None
    assert fake.invoked_with["context"] == {
        "vendor_id": "V-001",
        "model_id": agent.VERTEX_PRIMARY_MODEL,
    }
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


def test_token_split_includes_tool_internal_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool-internal model call's recorded ``usage`` folds into the run's billable split.

    The classifier records its structured-output call's usage on the trace (see
    classify_import_restriction); the run totals must cover it, or every cost figure
    understates the true billable spend by one model call.
    """
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    classify = _classify_spec()
    classify.output["usage"] = {"input_tokens": 300, "output_tokens": 60, "total_tokens": 360}
    fake = _FakeAgent(
        calls=[classify, _draft_spec("Grounded draft citing HTS 8517.13.0000.")],
        messages=[
            AIMessage(
                content="done",
                usage_metadata={"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
            )
        ],
    )
    _install_agent(monkeypatch, fake)

    result = agent.run_agent("V-001", "What duty applies to my declared electronics?")

    assert result.prompt_tokens == 400  # 100 loop + 300 classifier
    assert result.output_tokens == 100  # 40 loop + 60 classifier
    assert result.total_tokens == 500
    assert result.prompt_tokens + result.output_tokens == result.total_tokens
    assert len(captured) == 1
    assert captured[0].prompt_tokens == 400


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
    # No invocation exception fired (the loop just ran out of tool calls to make), so there
    # is nothing to classify - error_class stays None, distinct from an actual invoke error.
    assert result.error_class is None
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
    # An unrecognized exception classifies as UPSTREAM_ERROR, not RATE_LIMITED/TIMEOUT - the
    # API surfaces keep returning this fallback draft as a normal 200/done.
    assert result.error_class is RunErrorClass.UPSTREAM_ERROR
    assert len(captured) == 1  # a failed run still produces exactly one audit trace
    assert captured[0].error_class is RunErrorClass.UPSTREAM_ERROR


def test_invoke_failure_rate_limited_is_classified_on_the_result_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end wiring: a rate-limit exception from the model call flows through
    build_run_trace into both the persisted trace and the projected AgentResult."""
    _vendor_exists(monkeypatch)
    _stub_owner(monkeypatch, None)
    captured = _capture_traces(monkeypatch)

    fake = _FakeAgent(error=google_api_exceptions.ResourceExhausted("quota exceeded"))
    _install_agent(monkeypatch, fake)

    result = agent.run_agent("V-001", "What is the duty rate for cotton t-shirts?")

    assert result.error_class is RunErrorClass.RATE_LIMITED
    assert result.draft_response == agent._FALLBACK_DRAFT
    assert len(captured) == 1
    assert captured[0].error_class is RunErrorClass.RATE_LIMITED


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


def test_system_prompt_carries_the_cross_model_tool_mandates() -> None:
    """The prompt lines that keep every model arm on the tool rails stay present.

    Load-bearing for the non-Gemini eval arms: without the TOOL PROTOCOL block, Claude
    models call tools in parallel and answer in prose instead of drafting (observed live
    2026-07-18), so a run ends with no draft and degrades to the fallback. Pinning the
    key phrases keeps a future prompt edit from silently dropping the mandates.
    """
    prompt = agent._SYSTEM_PROMPT
    # Sequencing: classifier first, one tool per turn, never parallel.
    assert "ALWAYS call this first" in prompt
    assert "exactly ONE tool per turn" in prompt
    assert "NEVER call two tools in parallel" in prompt
    # Delivery: the draft tool is the only answer channel; a prose ending is a failure.
    assert "ONLY way to deliver your answer" in prompt
    assert "ends in plain text" in prompt


def test_system_prompt_forbids_band_by_analogy_for_unmatched_codes() -> None:
    """For an HTS code with no exact clause on record, the draft must decline a restriction.

    A live flash run (2026-07-20) exposed the loophole: told the exact code was not on
    record, the model still generalized a neighboring clause's band onto it ("such items
    typically require a license"), reading the hedge as permitted "context". The prompt now
    forbids attaching a band by analogy or hedge; pinning the phrases keeps a future edit
    from silently reopening the gap. The end-to-end proof is the ``unsupported_response``
    eval case; this is its hermetic guard.
    """
    prompt = agent._SYSTEM_PROMPT
    assert "CANNOT be determined" in prompt
    assert "generalized by analogy" in prompt
    assert "decide the asked code" in prompt


# --- classify_invoke_error -------------------------------------------------------
# Exception construction below uses the REAL SDK exception classes (verified against
# backend/.venv's installed sources - see classify_invoke_error's docstring), not stand-in
# subclasses, so a constructor-signature drift on a future SDK upgrade fails these tests
# rather than silently going unnoticed.


def _anthropic_status_error(
    cls: type[anthropic.APIStatusError], status_code: int
) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request)
    return cls("boom", response=response, body=None)


def test_classify_invoke_error_maps_anthropic_rate_limit() -> None:
    err = _anthropic_status_error(anthropic.RateLimitError, 429)
    assert agent.classify_invoke_error(err) is RunErrorClass.RATE_LIMITED


def test_classify_invoke_error_maps_anthropic_timeout() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APITimeoutError(request=request)
    assert agent.classify_invoke_error(err) is RunErrorClass.TIMEOUT


def test_classify_invoke_error_maps_google_api_core_resource_exhausted() -> None:
    """Defense-in-depth: this class is never actually raised by the langchain-google-genai
    seam in use (see the docstring), but is still checked in case a different Google client
    lands on this seam."""
    err = google_api_exceptions.ResourceExhausted("quota exceeded")
    assert agent.classify_invoke_error(err) is RunErrorClass.RATE_LIMITED


def test_classify_invoke_error_maps_google_api_core_deadline_exceeded() -> None:
    err = google_api_exceptions.DeadlineExceeded("deadline exceeded")
    assert agent.classify_invoke_error(err) is RunErrorClass.TIMEOUT


def test_classify_invoke_error_maps_httpx_timeout() -> None:
    """A bare network timeout below the HTTP-response level propagates unwrapped as
    httpx.TimeoutException on the live Gemini-on-Vertex path (verified in
    google/genai/_api_client.py's retry_args)."""
    err = httpx.TimeoutException("read timed out")
    assert agent.classify_invoke_error(err) is RunErrorClass.TIMEOUT


def test_classify_invoke_error_maps_google_genai_server_error_504_to_timeout() -> None:
    """The ACTUAL live-path type for a Vertex gateway timeout: google.genai.errors.ServerError
    is not caught/wrapped by langchain_google_genai, so it reaches here directly."""
    err = google_genai_errors.ServerError(504, {"message": "Deadline exceeded"})
    assert agent.classify_invoke_error(err) is RunErrorClass.TIMEOUT


def test_classify_invoke_error_treats_other_5xx_as_upstream_error() -> None:
    err = google_genai_errors.ServerError(503, {"message": "Service unavailable"})
    assert agent.classify_invoke_error(err) is RunErrorClass.UPSTREAM_ERROR


def test_classify_invoke_error_maps_google_genai_client_error_429_directly() -> None:
    """An unwrapped google.genai.errors.ClientError(429) classifies via the generic
    status/code fallback, independent of the wrapper the next test exercises."""
    err = google_genai_errors.ClientError(429, {"message": "Resource exhausted"})
    assert agent.classify_invoke_error(err) is RunErrorClass.RATE_LIMITED


def test_classify_invoke_error_unwraps_the_gemini_429_wrapper() -> None:
    """THE live shape for a Vertex 429: langchain_google_genai.chat_models
    ._handle_client_error catches the real ClientError(429) and re-raises
    ChatGoogleGenerativeAIError with `from e` (verified in the installed 4.2.6 source) -
    what run_agent/stream_agent_run actually catch is the wrapper, one __cause__ hop above
    the classifiable error. classify_invoke_error must walk down to it."""
    inner = google_genai_errors.ClientError(429, {"message": "Resource exhausted"})
    try:
        raise ChatGoogleGenerativeAIError(
            "Error calling model 'gemini-2.5-flash' (RESOURCE_EXHAUSTED)."
        ) from inner
    except ChatGoogleGenerativeAIError as wrapper:
        assert agent.classify_invoke_error(wrapper) is RunErrorClass.RATE_LIMITED


def test_classify_invoke_error_walks_implicit_context_chain() -> None:
    """A bare `raise` inside an `except` block (implicit chaining, no `from`) still links
    via __context__; the walk must follow that too, not just an explicit __cause__."""

    def _boom() -> None:
        try:
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APITimeoutError(request=request)
        except anthropic.APITimeoutError:
            raise RuntimeError("agent loop failed")  # noqa: B904 - implicit chaining is the point

    with pytest.raises(RuntimeError) as excinfo:
        _boom()
    assert agent.classify_invoke_error(excinfo.value) is RunErrorClass.TIMEOUT


class _FakeRetryWrapperError(Exception):
    """A stand-in for a hypothetical future retry-wrapper type this codebase has never seen.

    Not a real SDK class, deliberately: this test proves the generic status_code/code
    duck-typed fallback (not an isinstance check), so an SDK upgrade that changes the
    concrete wrapper type still classifies a 429 correctly as long as it exposes the code.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__("wrapped upstream failure")
        self.status_code = status_code


def test_classify_invoke_error_generic_429_attribute_is_rate_limited() -> None:
    assert agent.classify_invoke_error(_FakeRetryWrapperError(429)) is RunErrorClass.RATE_LIMITED


def test_classify_invoke_error_defaults_to_upstream_error() -> None:
    assert (
        agent.classify_invoke_error(RuntimeError("vertex transport blew up"))
        is RunErrorClass.UPSTREAM_ERROR
    )


# --- build_run_trace: error_class wiring -----------------------------------------
def _run_meta() -> agent.RunMeta:
    return agent.new_run("V-001", "Why is my shipment held?", None)


def _draft_call(text: str = "Grounded draft.") -> ToolCallLog:
    return ToolCallLog(
        tool_name="draft_clearance_response",
        input={"response_text": text},
        output={"trace_id": "tr-x", "status": "drafted"},
        duration_ms=5.0,
        timestamp="2026-07-19T00:00:00+00:00",
    )


def test_build_run_trace_sets_error_class_on_an_errored_run() -> None:
    trace = agent.build_run_trace(
        _run_meta(), (), [], google_api_exceptions.ResourceExhausted("quota exceeded")
    )
    assert trace.error_class is RunErrorClass.RATE_LIMITED
    assert trace.classification is not None
    assert trace.classification.intent is InquiryIntent.ITERATION_CAP_EXCEEDED


def test_build_run_trace_leaves_error_class_none_on_a_clean_run() -> None:
    trace = agent.build_run_trace(_run_meta(), (_draft_call(),), [], None)
    assert trace.draft_response == "Grounded draft."
    assert trace.error_class is None


def test_build_run_trace_leaves_error_class_none_on_a_plain_iteration_cap() -> None:
    """No draft AND no invocation exception (the loop just ran out of tool calls to make) -
    still ITERATION_CAP_EXCEEDED, but nothing to classify, so error_class stays None."""
    trace = agent.build_run_trace(_run_meta(), (), [], None)
    assert trace.classification is not None
    assert trace.classification.intent is InquiryIntent.ITERATION_CAP_EXCEEDED
    assert trace.error_class is None
