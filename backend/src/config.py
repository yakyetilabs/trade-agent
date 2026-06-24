"""Single configuration source.

Environment variables are read here exactly once at import time and re-exported as
typed, immutable constants. No other module in the application may call
``os.environ`` / ``os.getenv`` — import the constants from here instead.

The small pure helpers (``parse_allowlist``, ``resolve_cors_origins``) keep the
parsing logic unit-testable without mutating process environment state.
"""

import os
from typing import Final, Literal

type AppEnv = Literal["local", "production"]


def parse_allowlist(raw: str) -> frozenset[str]:
    """Compile a comma-separated email string into a lowercased, O(1)-lookup set."""
    return frozenset(email.strip().lower() for email in raw.split(",") if email.strip())


def resolve_cors_origins(app_env: AppEnv, prod_origin: str) -> tuple[str, ...]:
    """Local dev permits the Vite origin; production locks to the deployed frontend."""
    if app_env == "production":
        return (prod_origin,) if prod_origin else ()
    return ("http://localhost:5173", "http://127.0.0.1:5173")


def _normalize_app_env(raw: str) -> AppEnv:
    return "production" if raw.strip().lower() == "production" else "local"


# --- Raw env reads: the ONLY os.getenv calls permitted in the codebase ---------
_RAW_ALLOWED_USERS: Final[str] = os.getenv("TRADE_AGENT_ALLOWED_USERS", "")
_RAW_APP_ENV: Final[str] = os.getenv("APP_ENV", "local")
_RAW_PROD_ORIGIN: Final[str] = os.getenv("PROD_FRONTEND_ORIGIN", "")

# --- Exported, typed, immutable constants --------------------------------------
APP_ENV: Final[AppEnv] = _normalize_app_env(_RAW_APP_ENV)
ALLOWED_USERS: Final[frozenset[str]] = parse_allowlist(_RAW_ALLOWED_USERS)
CORS_ORIGINS: Final[tuple[str, ...]] = resolve_cors_origins(APP_ENV, _RAW_PROD_ORIGIN)

GCP_PROJECT: Final[str] = os.getenv("GCP_PROJECT", "trade-agent-demo")
GCP_REGION: Final[str] = os.getenv("GCP_REGION", "us-central1")

VERTEX_PRIMARY_MODEL: Final[str] = os.getenv("VERTEX_PRIMARY_MODEL", "gemini-2.5-flash")
VERTEX_EVAL_MODEL: Final[str] = os.getenv("VERTEX_EVAL_MODEL", "gemini-2.5-pro")
VERTEX_EMBEDDING_MODEL: Final[str] = os.getenv("VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
VERTEX_EMBEDDING_DIM: Final[int] = int(os.getenv("VERTEX_EMBEDDING_DIM", "768"))

PINECONE_API_KEY: Final[str] = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX: Final[str] = os.getenv("PINECONE_INDEX", "trade-agent-hts-kb")
