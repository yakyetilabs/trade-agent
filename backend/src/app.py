"""FastAPI application surface for the trade-agent backend.

The API is a public demo over synthetic data - there is no sign-in and no user identity.
The safety posture is in-app and deterministic instead: vendor scoping is bound
server-side into the agent's execution context (``VendorContext``), the pre-model
escalation guard intercepts flagged inquiries before any model call, dispositions are
draft-only until a human approves, and every run is audited to Firestore. Every
``/api/*`` route additionally sits behind the in-app per-IP rate limiter
(``src/ratelimit.py``); ``/health`` stays unlimited.

- ``POST /api/inquiry``                       run the agent for a chosen vendor
- ``POST /api/inquiry/stream``                run the agent, stream stages + reasoning
- ``GET  /api/vendors``                       all vendors (the scope picker)
- ``GET  /api/traces``                        recent audit traces, newest first
- ``POST /api/traces/{trace_id}/disposition`` human approve/reject
"""

from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src import repository
from src.agent import (
    RATE_LIMITED_CLIENT_MESSAGE,
    TIMEOUT_CLIENT_MESSAGE,
    AgentResult,
    UnknownVendorError,
    run_agent,
)
from src.config import APP_ENV, CORS_ORIGINS, VERTEX_PRIMARY_MODEL
from src.models import VENDOR_ID_PATTERN, AgentTrace, RunErrorClass, TraceDisposition, Vendor
from src.ratelimit import RateLimitDecision, rate_limiter, resolve_client_ip
from src.streaming import DoneEvent, ErrorEvent, sse_format, stream_agent_run

app = FastAPI(title="TradeOps AI backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Recent-trace page size for the AgentOps view - comfortably inside the Firestore
# free-tier read budget, served natively by order_by + limit (no client-side sort).
_RECENT_TRACES_LIMIT = 50


class HealthResponse(BaseModel):
    """Liveness payload - intentionally free of any vendor or user data."""

    status: str
    app_env: str
    primary_model: str


class InquiryRequest(BaseModel):
    """An inquiry scoped to a vendor chosen from the dropdown.

    ``vendor_id`` is pattern-validated here so a malformed scope is a 422 at the edge,
    never reaching the orchestrator; existence is checked downstream.
    """

    vendor_id: str = Field(pattern=VENDOR_ID_PATTERN)
    inquiry: str = Field(min_length=1, max_length=4000)


class DispositionRequest(BaseModel):
    """Human-review decision on a draft. Only approve/reject are caller-settable -
    ``draft``/``escalated`` are written by the agent, never by this endpoint."""

    disposition: Literal["approved", "rejected"]


class DispositionResponse(BaseModel):
    """Echoes the trace id and its new disposition after a human decision."""

    trace_id: str
    disposition: TraceDisposition


def enforce_rate_limit(request: Request, response: Response) -> RateLimitDecision:
    """Per-IP admission gate for every ``/api/*`` route: reserves one request from the
    caller's budget and refuses with 429 (``Retry-After`` + ``X-RateLimit-*``) when a
    budget is exhausted.

    The caller key is the RIGHTMOST ``X-Forwarded-For`` entry - the one Google's front
    end appends for the actually-connected peer (leading entries are caller-supplied and
    spoofable; the DNS-only ``api.`` origin has no proxy in front, so that peer is the
    real client). Successful admissions surface ``X-RateLimit-*`` via the injected
    ``response``; the streaming route re-attaches them itself, because FastAPI merges
    dependency-set headers only onto serialized responses, not onto a directly returned
    ``Response`` (verified against the installed FastAPI 0.138).
    """
    client_ip = resolve_client_ip(
        request.headers.get("x-forwarded-for"),
        request.client.host if request.client is not None else None,
    )
    decision = rate_limiter.check_and_reserve(client_ip)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for this IP. Try again shortly.",
            headers=decision.headers,
        )
    for name, value in decision.headers.items():
        response.headers[name] = value
    return decision


@app.get("/health")
def health() -> HealthResponse:
    """Liveness probe - never touches GCP."""
    return HealthResponse(
        status="ok",
        app_env=APP_ENV,
        primary_model=VERTEX_PRIMARY_MODEL,
    )


@app.post("/api/inquiry", response_model=AgentResult)
def submit_inquiry(
    request: InquiryRequest,
    admission: Annotated[RateLimitDecision, Depends(enforce_rate_limit)],
) -> AgentResult:
    """Run the agent pipeline for one inquiry, scoped to the chosen vendor.

    ``vendor_id`` is bound server-side into ``VendorContext`` before the graph runs,
    so the model never sees an unscoped data pool. A run is synchronous (the model call
    dominates), so FastAPI dispatches this sync handler to its worker threadpool,
    keeping the trace ``ContextVar`` on one thread. The run's actual token usage is
    debited against the caller's TPM budget after it returns.

    The trace is already persisted (full audit) by the time a RATE_LIMITED/TIMEOUT
    ``error_class`` turns into a 503 here - the audit trail stays complete even though the
    client sees an honest error instead of the generic fallback draft. UPSTREAM_ERROR keeps
    today's behavior: the fallback draft is returned as a normal 200.
    """
    try:
        result = run_agent(request.vendor_id, request.inquiry)
    except UnknownVendorError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown vendor: {exc.vendor_id}",
        ) from exc
    # Tokens may have been consumed even on a degraded run, so debit before raising.
    rate_limiter.debit_tokens(admission.client_ip, result.total_tokens or 0)
    if result.error_class is RunErrorClass.RATE_LIMITED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RATE_LIMITED_CLIENT_MESSAGE,
            headers={"Retry-After": "60"},
        )
    if result.error_class is RunErrorClass.TIMEOUT:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=TIMEOUT_CLIENT_MESSAGE,
        )
    return result


@app.post("/api/inquiry/stream")
async def submit_inquiry_stream(
    request: InquiryRequest,
    admission: Annotated[RateLimitDecision, Depends(enforce_rate_limit)],
) -> StreamingResponse:
    """Streaming variant of ``POST /api/inquiry``: a ``text/event-stream`` of
    pipeline-stage progress plus the model's streamed reasoning and answer deltas,
    ending in a ``done`` event carrying the ``AgentResult`` (see ``src/streaming.py``
    for the event contract).

    Once streaming, an unknown vendor or an unexpected failure surfaces as a terminal
    ``error`` event (the status is already 200). The stream reaches the browser through
    the DNS-only ``api.`` origin - no CDN in the path - and the headers below ask any
    other intermediary not to buffer or cache it.
    """

    async def _events() -> AsyncIterator[str]:
        total_tokens = 0
        try:
            async for event in stream_agent_run(request.vendor_id, request.inquiry):
                if isinstance(event, DoneEvent) and event.result.total_tokens:
                    total_tokens = event.result.total_tokens
                elif isinstance(event, ErrorEvent) and event.total_tokens:
                    # A RATE_LIMITED/TIMEOUT run ends in an error event instead of done,
                    # but its consumed tokens still settle against the caller's budget
                    # (parity with the sync path, which debits before raising its 503).
                    total_tokens = event.total_tokens
                yield sse_format(event)
        finally:
            # A run's cost is knowable only from the terminal event, so the TPM
            # budget settles when the stream closes (client disconnects included).
            rate_limiter.debit_tokens(admission.client_ip, total_tokens)

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        # no-store: never cache a live run. X-Accel-Buffering=no asks any intermediary
        # proxy not to buffer, so stages arrive live (confirmed end-to-end in F5).
        # X-RateLimit-* attach here directly: FastAPI does not merge dependency-set
        # headers onto a directly returned Response (see enforce_rate_limit).
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", **admission.headers},
    )


@app.get(
    "/api/vendors",
    response_model=list[Vendor],
    dependencies=[Depends(enforce_rate_limit)],
)
def list_vendors() -> list[Vendor]:
    """List all vendors - the scope-selection dropdown for the public demo."""
    return repository.list_vendors()


@app.get(
    "/api/traces",
    response_model=list[AgentTrace],
    dependencies=[Depends(enforce_rate_limit)],
)
def list_traces() -> list[AgentTrace]:
    """Return recent audit traces, newest first - the public observability surface."""
    return repository.list_recent_traces(_RECENT_TRACES_LIMIT)


@app.post(
    "/api/traces/{trace_id}/disposition",
    response_model=DispositionResponse,
    dependencies=[Depends(enforce_rate_limit)],
)
def set_trace_disposition(trace_id: str, request: DispositionRequest) -> DispositionResponse:
    """Record a human reviewer's approve/reject decision - the mandatory handoff that
    flips a draft out of the agent's hands. A 404 means no such trace."""
    trace = repository.get_trace(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown trace: {trace_id}",
        )
    disposition = TraceDisposition(request.disposition)
    repository.update_trace_disposition(trace_id, disposition)
    return DispositionResponse(trace_id=trace_id, disposition=disposition)
