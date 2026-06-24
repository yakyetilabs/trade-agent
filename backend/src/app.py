"""FastAPI application surface for the trade-agent backend.

Phase 1 exposes only the perimeter: an open liveness probe and a single protected
route that proves the Firebase-Admin + allowlist boundary. The agent endpoints are
added in later phases behind the same ``verify_authorized_analyst`` dependency.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.config import APP_ENV, CORS_ORIGINS, VERTEX_PRIMARY_MODEL
from src.security import verify_authorized_analyst

app = FastAPI(title="trade-agent backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """Liveness payload — intentionally free of any vendor or user data."""

    status: str
    app_env: str
    primary_model: str


class IdentityResponse(BaseModel):
    """Returned by the protected probe to confirm the verified analyst identity."""

    email: str
    authorized: bool


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
