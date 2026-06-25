"""FastAPI application surface for the trade-agent backend.

The perimeter is an open liveness probe plus the analyst-facing API, every route of
which sits behind the ``verify_authorized_analyst`` dependency (Firebase-Admin token
verification + the in-memory allowlist). The agent endpoints resolve a vendor scope
from the request, run the LangGraph pipeline, and expose the audit trail:

- ``POST /api/inquiry``                     run the agent for one inquiry
- ``GET  /api/vendors``                     populate the analyst's vendor picker
- ``GET  /api/traces``                      recent audit traces for the AgentOps view
- ``POST /api/traces/{trace_id}/disposition`` human approve/reject of a draft
"""

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from google.api_core.exceptions import NotFound
from pydantic import BaseModel, Field

from src import repository
from src.agent import AgentResult, UnknownVendorError, run_agent
from src.config import APP_ENV, CORS_ORIGINS, VERTEX_PRIMARY_MODEL
from src.models import VENDOR_ID_PATTERN, AgentTrace, TraceDisposition, Vendor
from src.security import verify_authorized_analyst

app = FastAPI(title="trade-agent backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Recent-trace page size for the AgentOps view — comfortably inside the Firestore
# free-tier read budget, served natively by order_by + limit (no client-side sort).
_RECENT_TRACES_LIMIT = 50


class HealthResponse(BaseModel):
    """Liveness payload — intentionally free of any vendor or user data."""

    status: str
    app_env: str
    primary_model: str


class IdentityResponse(BaseModel):
    """Returned by the protected probe to confirm the verified analyst identity."""

    email: str
    authorized: bool


class InquiryRequest(BaseModel):
    """An analyst inquiry scoped to a vendor chosen from the dropdown.

    ``vendor_id`` is pattern-validated here so a malformed scope is a 422 at the edge,
    never reaching the orchestrator; existence against Firestore is checked downstream.
    """

    vendor_id: str = Field(pattern=VENDOR_ID_PATTERN)
    inquiry: str = Field(min_length=1, max_length=4000)


class DispositionRequest(BaseModel):
    """Human-review decision on a draft. Only approve/reject are caller-settable —
    ``draft``/``escalated`` are written by the agent, never by this endpoint."""

    disposition: Literal["approved", "rejected"]


class DispositionResponse(BaseModel):
    """Echoes the trace id and its new disposition after a human decision."""

    trace_id: str
    disposition: TraceDisposition


@app.get("/health")
def health() -> HealthResponse:
    """Unauthenticated liveness probe — never touches GCP or the allowlist."""
    return HealthResponse(
        status="ok",
        app_env=APP_ENV,
        primary_model=VERTEX_PRIMARY_MODEL,
    )


@app.get("/api/me")
def whoami(email: str = Depends(verify_authorized_analyst)) -> IdentityResponse:
    """Protected probe: reaching this means the auth boundary admitted the caller."""
    return IdentityResponse(email=email, authorized=True)


@app.post("/api/inquiry", response_model=AgentResult)
def submit_inquiry(
    request: InquiryRequest,
    _analyst: str = Depends(verify_authorized_analyst),
) -> AgentResult:
    """Run the agent pipeline for one inquiry and return its outcome.

    A run is synchronous (the model call dominates), so FastAPI dispatches this sync
    handler to its worker threadpool — keeping the trace ``ContextVar`` on one thread.
    """
    try:
        return run_agent(request.vendor_id, request.inquiry)
    except UnknownVendorError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown vendor: {exc.vendor_id}",
        ) from exc


@app.get("/api/vendors", response_model=list[Vendor])
def list_vendors(_analyst: str = Depends(verify_authorized_analyst)) -> list[Vendor]:
    """List every vendor — backs the analyst's scope-selection dropdown."""
    return repository.list_vendors()


@app.get("/api/traces", response_model=list[AgentTrace])
def list_traces(_analyst: str = Depends(verify_authorized_analyst)) -> list[AgentTrace]:
    """Return the most recent audit traces, newest first, for the AgentOps view."""
    return repository.list_recent_traces(_RECENT_TRACES_LIMIT)


@app.post("/api/traces/{trace_id}/disposition", response_model=DispositionResponse)
def set_trace_disposition(
    trace_id: str,
    request: DispositionRequest,
    _analyst: str = Depends(verify_authorized_analyst),
) -> DispositionResponse:
    """Record a human reviewer's approve/reject decision — the mandatory handoff that
    flips a draft out of the agent's hands. A 404 means no such trace exists."""
    disposition = TraceDisposition(request.disposition)
    try:
        repository.update_trace_disposition(trace_id, disposition)
    except NotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown trace: {trace_id}",
        ) from exc
    return DispositionResponse(trace_id=trace_id, disposition=disposition)
