"""FastAPI application surface for the trade-agent backend.

The perimeter is an open liveness probe plus the analyst-facing API. Every route sits
behind two layers of the security boundary:

1. ``verify_authorized_analyst`` — *who* may use the app at all (Firebase-Admin token
   verification + the in-memory allowlist).
2. ``analyst_can_access_vendor`` — *which vendor* an authorized analyst may act on.
   Every endpoint that touches vendor-scoped data enforces this, so an analyst can only
   query, list, audit, and dispose of records for vendors in their authorized scope:

- ``POST /api/inquiry``                       run the agent (403 + audit log if out of scope)
- ``GET  /api/vendors``                       the analyst's authorized vendors (the picker)
- ``GET  /api/traces``                        recent audit traces, filtered to that scope
- ``POST /api/traces/{trace_id}/disposition`` human approve/reject (scoped to the trace's vendor)

Scope is resolved server-side from the analyst's verified identity — never from a
client-supplied claim — so the dropdown filtering is UX and these checks are the boundary.
"""

import logging
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import repository
from src.agent import AgentResult, UnknownVendorError, run_agent
from src.config import APP_ENV, CORS_ORIGINS, VERTEX_PRIMARY_MODEL
from src.models import VENDOR_ID_PATTERN, AgentTrace, TraceDisposition, Vendor
from src.security import analyst_can_access_vendor, verify_authorized_analyst

_logger = logging.getLogger(__name__)

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
    never reaching the orchestrator; authorization and existence are checked downstream.
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
    analyst_email: str = Depends(verify_authorized_analyst),
) -> AgentResult:
    """Run the agent pipeline for one inquiry, scoped to the analyst's authorized vendor.

    An out-of-scope vendor is refused with a 403 *before* any model or Firestore work and
    a structured scope-violation log — the audit signal a reviewer expects to stay at zero.
    A run is synchronous (the model call dominates), so FastAPI dispatches this sync handler
    to its worker threadpool, keeping the trace ``ContextVar`` on one thread.
    """
    if not analyst_can_access_vendor(analyst_email, request.vendor_id):
        _logger.warning(
            "scope_violation: analyst=%s requested vendor=%s outside authorized scope",
            analyst_email,
            request.vendor_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for the requested vendor scope.",
        )
    try:
        return run_agent(request.vendor_id, request.inquiry)
    except UnknownVendorError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown vendor: {exc.vendor_id}",
        ) from exc


@app.get("/api/vendors", response_model=list[Vendor])
def list_vendors(analyst_email: str = Depends(verify_authorized_analyst)) -> list[Vendor]:
    """List the vendors THIS analyst is authorized for — the scope-selection dropdown.

    Filtering here is UX; the authoritative gate is the per-request check on every
    vendor-scoped endpoint. An admin (``*`` grant) sees all vendors.
    """
    return [
        vendor
        for vendor in repository.list_vendors()
        if analyst_can_access_vendor(analyst_email, vendor.vendor_id)
    ]


@app.get("/api/traces", response_model=list[AgentTrace])
def list_traces(analyst_email: str = Depends(verify_authorized_analyst)) -> list[AgentTrace]:
    """Return recent audit traces for vendors in this analyst's scope, newest first."""
    return [
        trace
        for trace in repository.list_recent_traces(_RECENT_TRACES_LIMIT)
        if analyst_can_access_vendor(analyst_email, trace.vendor_id)
    ]


@app.post("/api/traces/{trace_id}/disposition", response_model=DispositionResponse)
def set_trace_disposition(
    trace_id: str,
    request: DispositionRequest,
    analyst_email: str = Depends(verify_authorized_analyst),
) -> DispositionResponse:
    """Record a human reviewer's approve/reject decision — the mandatory handoff that flips
    a draft out of the agent's hands. Scoped to the trace's vendor: a 404 means no such
    trace; a 403 means it belongs to a vendor outside the reviewer's authorized scope."""
    trace = repository.get_trace(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown trace: {trace_id}",
        )
    if not analyst_can_access_vendor(analyst_email, trace.vendor_id):
        _logger.warning(
            "scope_violation: analyst=%s attempted disposition on trace=%s vendor=%s out of scope",
            analyst_email,
            trace_id,
            trace.vendor_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this trace's vendor scope.",
        )
    disposition = TraceDisposition(request.disposition)
    repository.update_trace_disposition(trace_id, disposition)
    return DispositionResponse(trace_id=trace_id, disposition=disposition)
