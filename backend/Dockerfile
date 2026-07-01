# Cloud Run backend image: FastAPI + LangGraph agent under uvicorn.
#
# Why a Dockerfile, not Cloud Run buildpacks: the Python buildpack doesn't install uv (our
# resolver), and its runtime registry doesn't carry every exact CPython patch - a Dockerfile
# gives uv's lockfile-pinned installs, an exact interpreter from Docker Hub, and a reviewable
# build. `gcloud run deploy --source=backend` auto-prefers this Dockerfile over buildpacks.
#
# BuildKit-independent on purpose (plain COPY-layer caching, no `RUN --mount` cache mounts):
# Cloud Build runs each build on a fresh VM so a uv cache mount wouldn't persist, and this
# keeps the build portable across any builder (local `docker build`, Cloud Build, etc.).

# Exact CPython patch pin (3.12 is security-only; bump deliberately for CVEs) so the base
# is as reproducible as our lockfile-pinned deps.
FROM python:3.12.13-slim-bookworm

# Pin uv to the version that authored uv.lock (`uv --version`); bump in lockstep with re-locks.
COPY --from=ghcr.io/astral-sh/uv:0.7.18 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Deps layer, cached independently of source. --no-dev drops the pytest/ruff/pyright group;
# --no-install-project pairs with `[tool.uv] package = false` (flat-src app, nothing to build).
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

# Least-privilege runtime (matches the project's security-first posture).
RUN useradd --system --no-create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# venv on PATH -> run uvicorn directly (uv not needed at runtime). src.app resolves from
# WORKDIR /app, exactly as it does locally from backend/.
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

# sh -c so Cloud Run's $PORT expands (default 8080 for local runs); `exec` gives uvicorn PID 1
# so it receives SIGTERM for a graceful drain on scale-to-zero.
CMD ["sh", "-c", "exec uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
