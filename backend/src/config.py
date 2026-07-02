"""Single configuration source.

Environment variables are read here exactly once at import time and re-exported as
typed, immutable constants. No other module in the application may call
``os.environ`` / ``os.getenv`` — import the constants from here instead.

The small pure helpers (``parse_analyst_scopes``, ``resolve_cors_origins``) keep the
parsing logic unit-testable without mutating process environment state.
"""

import os
from typing import Final, Literal

type AppEnv = Literal["local", "production"]

# An analyst authorized for every vendor (admin) carries this wildcard in place of an
# explicit vendor list. It is matched verbatim by the scope check in ``security.py``.
WILDCARD_VENDOR_SCOPE: Final[str] = "*"


def parse_analyst_scopes(raw: str) -> dict[str, frozenset[str]]:
    """Compile the analyst->vendors authorization map from its env string.

    Format ``email=V-001,V-002;email2=*`` — analyst entries split on ``;``, the email
    and its vendor list on ``=``, vendor ids on ``,``. Emails are lowercased, vendor ids
    uppercased; a lone ``*`` grants every vendor (admin). This map is BOTH the identity
    allowlist (its keys decide who may use the app) AND each analyst's permissible vendor
    scope — one in-memory, O(1) source of truth for "who" and "what".
    """
    scopes: dict[str, frozenset[str]] = {}
    for entry in raw.split(";"):
        email_part, separator, vendor_part = entry.partition("=")
        email = email_part.strip().lower()
        if not email or not separator:
            continue
        vendors = frozenset(v.strip().upper() for v in vendor_part.split(",") if v.strip())
        if vendors:
            scopes[email] = vendors
    return scopes


def resolve_cors_origins(app_env: AppEnv, prod_origins: str) -> tuple[str, ...]:
    """Local dev permits the Vite origin; production locks to the deployed frontend origins.

    Prod is a comma-separated list because the frontend is served from more than one host
    (the custom domain plus Firebase's default ``*.web.app`` / ``*.firebaseapp.com``) - each
    is a distinct browser origin under the CORS spec, so each needs an explicit allow entry.
    An empty value returns ``()`` (no cross-origin access), which is the safe default for a
    misconfigured deploy.
    """
    if app_env == "production":
        return tuple(o.strip() for o in prod_origins.split(",") if o.strip())
    return ("http://localhost:5173", "http://127.0.0.1:5173")


def _normalize_app_env(raw: str) -> AppEnv:
    return "production" if raw.strip().lower() == "production" else "local"


# --- Raw env reads: the ONLY os.getenv calls permitted in the codebase ---------
_RAW_ANALYST_SCOPES: Final[str] = os.getenv("TRADE_AGENT_ANALYST_SCOPES", "")
_RAW_APP_ENV: Final[str] = os.getenv("APP_ENV", "local")
_RAW_PROD_ORIGINS: Final[str] = os.getenv("PROD_FRONTEND_ORIGINS", "")

# --- Exported, typed, immutable constants --------------------------------------
APP_ENV: Final[AppEnv] = _normalize_app_env(_RAW_APP_ENV)
# The analyst->vendors authorization map, plus the identity allowlist derived from its
# keys (being a key == permission to use the app at all).
ANALYST_VENDOR_SCOPES: Final[dict[str, frozenset[str]]] = parse_analyst_scopes(_RAW_ANALYST_SCOPES)
ALLOWED_USERS: Final[frozenset[str]] = frozenset(ANALYST_VENDOR_SCOPES.keys())
CORS_ORIGINS: Final[tuple[str, ...]] = resolve_cors_origins(APP_ENV, _RAW_PROD_ORIGINS)

GCP_PROJECT: Final[str] = os.getenv("GCP_PROJECT", "trade-agent-ff12a")
GCP_REGION: Final[str] = os.getenv("GCP_REGION", "us-central1")

# Chat + eval models are Gemini on Vertex AI (via langchain-google-genai, vertexai=True).
# One provider seam binds them: src/model_provider.py. Do not duplicate these ids elsewhere.
VERTEX_PRIMARY_MODEL: Final[str] = os.getenv("VERTEX_PRIMARY_MODEL", "gemini-2.5-flash")
VERTEX_EVAL_MODEL: Final[str] = os.getenv("VERTEX_EVAL_MODEL", "gemini-2.5-pro")

# Embeddings also on Gemini; the Pinecone index is fixed at 768 dims.
VERTEX_EMBEDDING_MODEL: Final[str] = os.getenv("VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
VERTEX_EMBEDDING_DIM: Final[int] = int(os.getenv("VERTEX_EMBEDDING_DIM", "768"))

PINECONE_API_KEY: Final[str] = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: Final[str] = os.getenv("PINECONE_INDEX", "trade-agent-hts-kb")

# Firestore collection names — fixed, not env-tunable. They carry the mandatory
# ``trade-agent-`` isolation prefix and are the single source for collection ids.
FIRESTORE_VENDORS_COLLECTION: Final[str] = "trade-agent-Vendors"
FIRESTORE_SHIPMENTS_COLLECTION: Final[str] = "trade-agent-Shipments"
FIRESTORE_TRACES_COLLECTION: Final[str] = "trade-agent-AgentTraces"
