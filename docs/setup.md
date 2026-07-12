# Setup

How to run TradeOps AI locally and deploy your own instance.
This guide covers the developer workflow; the one-time cloud provisioning (projects, APIs, service accounts, domains) is documented step by step in [GCP_SETUP.md](GCP_SETUP.md).

## Prerequisites

- **Python 3.12** and [`uv`](https://docs.astral.sh/uv/) for the backend.
- **Node 20+** and [`pnpm`](https://pnpm.io/) for the frontend.
- A **Google Cloud project** with Firestore (Native mode) and Vertex AI enabled.
- A **Pinecone** account with one serverless index at **768 dimensions** (cosine metric).
- The `gcloud` CLI, authenticated against your project, if you plan to deploy.

## 1. Install dependencies

```bash
cd backend && uv sync          # creates .venv from the lockfile
cd ../frontend && pnpm install
```

## 2. Configure the backend environment

Copy the template and fill it in:

```bash
cp backend/.env.example backend/.env
```

| Variable | What it is |
| --- | --- |
| `GCP_PROJECT` / `GCP_REGION` | Your GCP project id and region (Vertex AI + Firestore). |
| `VERTEX_PRIMARY_MODEL` / `VERTEX_EVAL_MODEL` | The chat models for the agent loop and the eval comparison run. |
| `VERTEX_EMBEDDING_MODEL` / `VERTEX_EMBEDDING_DIM` | The embedding model and dimension; must match the Pinecone index. |
| `PINECONE_API_KEY` / `PINECONE_INDEX` | The knowledge-base index credentials. |
| `RATE_LIMIT_RPM` / `RATE_LIMIT_TPM` / `RATE_LIMIT_WINDOW_SECONDS` | Per-IP limiter tuning; defaults are compiled into `src/config.py`, set these only to override. |
| `APP_ENV` | `local` relaxes CORS to the Vite dev origin; `production` locks it to `PROD_FRONTEND_ORIGINS`. |
| `PROD_FRONTEND_ORIGINS` | Comma-separated browser origins allowed by CORS in production. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Local dev only: path to a service-account key with Firestore + Vertex roles. Omit it to fall back to your own ADC (`gcloud auth application-default login`). Cloud Run uses its attached service account instead. |

All environment variables are read exactly once, at boot, in `backend/src/config.py`; that file is the source of truth for names, defaults, and current model ids.

The frontend needs no local configuration: the Vite dev server proxies `/api` to the backend same-origin.
`frontend/.env.production` (committed; contains only the public API hostname) bakes the production API base URL into the build.

## 3. Seed the synthetic data

Both scripts are idempotent and generate everything from fixed-seed RNG, so the dataset is fully reproducible:

```bash
cd backend
uv run --env-file .env python -m scripts.seed_firestore   # vendors + shipments -> Firestore
uv run --env-file .env python -m scripts.ingest_kb        # HTS clauses -> embeddings -> Pinecone
```

## 4. Run the dev servers

```bash
cd backend && uv run --env-file .env fastapi dev src/app.py   # API on http://127.0.0.1:8000
cd frontend && pnpm dev                                       # console on http://localhost:5173
```

Open http://localhost:5173, pick a vendor, and run an inquiry.

## 5. Quality gates

Run both before committing:

```bash
bash backend/verify.sh
# ruff check, ruff format --check, pyright (reportDeprecated=error), pytest

cd frontend
pnpm run typecheck && pnpm run lint && pnpm test && pnpm run build
```

## 6. Run the evaluation suite

```bash
cd backend && uv run --env-file .env python -m eval.run_eval
```

This executes the version-controlled cases in `eval/cases.json` against both configured models and writes reports to `eval/results/` (gitignored).

## 7. Deploy

**Backend (Cloud Run):**

```bash
bash backend/deploy.sh
```

The script wraps `gcloud run deploy --source=backend` with the production flags: the instance ceiling and concurrency cap, the env-vars file, and the Pinecone key mounted from Secret Manager.
`backend/Dockerfile` gives a lockfile-pinned, reproducible build.

**Frontend (Firebase Hosting), from the repo root:**

```bash
pnpm -C frontend build
firebase deploy --only hosting
```

The API is served cross-origin from a DNS-only subdomain (no CDN in front) so the SSE stream stays unbuffered; the frontend origin must be listed in `PROD_FRONTEND_ORIGINS`.
Domain mapping, DNS records, secrets, quotas, and the reasoning behind the split-origin layout are covered in [GCP_SETUP.md](GCP_SETUP.md) and [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) §9.
