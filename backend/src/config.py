"""Single configuration source.

Environment variables are read here exactly once at import time and re-exported as
typed, immutable constants. No other module in the application may call
``os.environ`` / ``os.getenv`` - import the constants from here instead.

The small pure helper (``resolve_cors_origins``) keeps the parsing logic
unit-testable without mutating process environment state.
"""

import os
from typing import Final, Literal

type AppEnv = Literal["local", "production"]


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
_RAW_APP_ENV: Final[str] = os.getenv("APP_ENV", "local")
_RAW_PROD_ORIGINS: Final[str] = os.getenv("PROD_FRONTEND_ORIGINS", "")

# --- Exported, typed, immutable constants --------------------------------------
APP_ENV: Final[AppEnv] = _normalize_app_env(_RAW_APP_ENV)
CORS_ORIGINS: Final[tuple[str, ...]] = resolve_cors_origins(APP_ENV, _RAW_PROD_ORIGINS)

GCP_PROJECT: Final[str] = os.getenv("GCP_PROJECT", "trade-agent-ff12a")
GCP_REGION: Final[str] = os.getenv("GCP_REGION", "us-central1")

# Chat + eval models are Gemini on Vertex AI (via langchain-google-genai, vertexai=True).
# One provider seam binds them: src/model_provider.py. Do not duplicate these ids elsewhere.
VERTEX_PRIMARY_MODEL: Final[str] = os.getenv("VERTEX_PRIMARY_MODEL", "gemini-2.5-flash")
VERTEX_EVAL_MODEL: Final[str] = os.getenv("VERTEX_EVAL_MODEL", "gemini-2.5-pro")

# Claude on Vertex AI - eval-only comparison arms (the serving path never reads these;
# only the eval runner passes them through run_agent's model_id seam). Vertex publishes
# dated snapshots with an "@" version separator, unlike the first-party "-" ids.
CLAUDE_HAIKU_MODEL: Final[str] = os.getenv("CLAUDE_HAIKU_MODEL", "claude-haiku-4-5@20251001")
CLAUDE_SONNET_MODEL: Final[str] = os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-5@20250929")
# Anthropic-on-Vertex serves from the global endpoint, not a pinned region.
ANTHROPIC_VERTEX_REGION: Final[str] = os.getenv("ANTHROPIC_VERTEX_REGION", "global")

# Embeddings also on Gemini; the Pinecone index is fixed at 768 dims.
VERTEX_EMBEDDING_MODEL: Final[str] = os.getenv("VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
VERTEX_EMBEDDING_DIM: Final[int] = int(os.getenv("VERTEX_EMBEDDING_DIM", "768"))

PINECONE_API_KEY: Final[str] = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: Final[str] = os.getenv("PINECONE_INDEX", "trade-agent-hts-kb")

# In-app per-IP rate limiter (src/ratelimit.py; docs/DESIGN_DECISIONS.md §11). RPM caps
# requests across all /api/* routes; TPM budgets model tokens on the inquiry endpoints;
# the window is the refill horizon - bucket capacity equals the full-window quota.
RATE_LIMIT_RPM: Final[int] = int(os.getenv("RATE_LIMIT_RPM", "30"))
RATE_LIMIT_TPM: Final[int] = int(os.getenv("RATE_LIMIT_TPM", "30000"))
RATE_LIMIT_WINDOW_SECONDS: Final[float] = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# Firestore collection names - fixed, not env-tunable. They carry the mandatory
# ``trade-agent-`` isolation prefix and are the single source for collection ids.
FIRESTORE_VENDORS_COLLECTION: Final[str] = "trade-agent-Vendors"
FIRESTORE_SHIPMENTS_COLLECTION: Final[str] = "trade-agent-Shipments"
FIRESTORE_TRACES_COLLECTION: Final[str] = "trade-agent-AgentTraces"
