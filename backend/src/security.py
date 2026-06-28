"""Zero-trust authorization boundary.

A FastAPI dependency verifies the incoming Firebase ID token via the Admin SDK
(which validates issuer, audience ``= <project-id>``, signature against Firebase's
rotating public keys, and expiry), then checks the resulting email against the
in-memory allowlist before any downstream LLM or Firestore work can run.

The O(1) allowlist lookup is what insulates the free-tier quota and Vertex credits
from unauthorized traffic without a per-request database read.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth

from src.config import ALLOWED_USERS, ANALYST_VENDOR_SCOPES, WILDCARD_VENDOR_SCOPE
from src.gcp.client import get_firebase_app

_bearer = HTTPBearer(auto_error=True)


def verify_authorized_analyst(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    """Decode the Firebase JWT, enforce the allowlist, and return the verified email."""
    get_firebase_app()  # ensure the Admin SDK is initialized exactly once
    token: str = credentials.credentials
    try:
        decoded: dict[str, object] = auth.verify_id_token(token)
        email: str = str(decoded.get("email", "")).lower()

        # O(1) memory lookup — completely bypasses Firestore read fees.
        if email not in ALLOWED_USERS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Account is not on the system allowlist.",
            )
        return email

    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - any verification failure collapses to 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
        ) from exc


def analyst_can_access_vendor(email: str, vendor_id: str) -> bool:
    """Return whether this analyst's authorized scope includes ``vendor_id``.

    The authorization companion to :func:`verify_authorized_analyst`: identity decides
    *who* may use the app; this decides *which vendor* an authorized analyst may act on.
    A ``*`` grant (admin) matches every vendor. Resolved entirely from the in-memory
    scope map — no Firestore read, keeping the auth path off the per-request quota.
    """
    scope = ANALYST_VENDOR_SCOPES.get(email.lower(), frozenset())
    return WILDCARD_VENDOR_SCOPE in scope or vendor_id in scope
