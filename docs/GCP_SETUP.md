# GCP & Pinecone Setup - Manual Runbook

This is the step-by-step manual setup for the `trade-agent` stack. Provisioning is deliberately by
console plus single-line CLI deploy scripts, not managed IaC, so there is **no Terraform**. At this
surface - one Cloud Run service, one Firestore database, one Pinecone index - Terraform would add
ceremony without payoff; it is the obvious first addition once the surface grows enough to warrant it.

Everything lives in **one** project - `trade-agent-ff12a`. A Firebase project _is_ a GCP project,
so Firestore, Cloud Run, and Firebase Hosting all share one identity, billing account, and quota.

> 💡 **Bounding a public endpoint.** The API is public and unauthenticated, so its resource envelope is
> capped by design rather than by a login: Cloud Run scales to zero under a hard instance ceiling, an
> in-app per-IP rate limiter throttles hostile traffic, and per-request input caps bound each call (§9).
> Vertex AI inference is the only usage-metered dependency, and those same controls bound it - so abuse
> cannot translate into unbounded resource consumption. Full rationale in `DESIGN_DECISIONS.md` §11.

---

## 0. Prerequisites

Local tooling:

```bash
gcloud --version        # Google Cloud CLI
firebase --version      # Firebase CLI  (npm i -g firebase-tools)
uv --version            # Python 3.12 package manager
pnpm --version          # Node package manager
```

Accounts you already have: a Google Cloud account and a Pinecone account.

Conventions used below:

- **Project display name:** `trade-agent`
- **Project ID:** `trade-agent-ff12a` (Firebase auto-appended `-ff12a` because `trade-agent` was
  taken globally; the ID is immutable and is what `GCP_PROJECT` / the token audience must equal)
- **GCP region:** `us-central1`
- **Resource prefix:** every GCP resource is named with the `trade-agent-` prefix (a non-negotiable project naming convention for account-level isolation).

---

## 1. Create the project & link billing

> 💡 **Two ways in - pick one.** If you start by adding Firebase (Step 3), it provisions the underlying
> GCP project for you and you can skip this step. The commands below are the standalone equivalent for
> creating the project directly. Don't do both.

**Console:** https://console.cloud.google.com → project picker → **New Project** → display name `trade-agent`
(the resulting ID is `trade-agent-ff12a`). Then **Billing** → link your billing account.

**CLI equivalent:**

```bash
gcloud projects create trade-agent-ff12a --name="trade-agent"
gcloud config set project trade-agent-ff12a
# Link billing (find your account id with: gcloud billing accounts list)
gcloud billing projects link trade-agent-ff12a --billing-account=XXXXXX-XXXXXX-XXXXXX
```

---

## 2. Enable the APIs

**Console:** APIs & Services → Enable APIs. **CLI (faster):**

```bash
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --project=trade-agent-ff12a
```

- `run` - Cloud Run (backend container)
- `aiplatform` - Vertex AI (Gemini 2.5 Flash/Pro + `gemini-embedding-001`)
- `firestore` - state + audit store
- `artifactregistry` - container image storage (Container Registry / `gcr.io` is retired; use Artifact Registry)
- `cloudbuild` - image build during `gcloud run deploy --source`
- `secretmanager` - the Pinecone API key at runtime, mounted into Cloud Run via `--set-secrets` (see §9)

This is a public, no-auth demo, so no Identity Platform / Firebase Auth API is needed (see §3).

---

## 3. Add Firebase to the project

**Console:** https://console.firebase.google.com → **Add project** → select the existing `trade-agent-ff12a`
GCP project (do **not** create a new one). The project must be on the **Blaze** (pay-as-you-go) plan,
which both Vertex AI and Cloud Run require.

Firebase is used for **Hosting only**.

> **Hosting only - no Authentication.** This is a public, no-auth demo, so you do not enable any Auth
> provider, and the frontend needs no registered Web App or `firebaseConfig` values. The public
> endpoint is bounded app-side instead of behind a login; the reasoning is in `DESIGN_DECISIONS.md` §11.

---

## 4. Firestore (Native mode) + collections

**Console:** Firebase or GCP console → **Firestore → Create database** →
**Native mode** → location `us-central1` (single-region) → **Production mode** rules.

Firestore provides one default database per project; create it in `us-central1` to match Cloud Run.

Create the three collections (they can also be created lazily by the seed scripts, but creating them now
makes the console navigable):

- `trade-agent-Vendors`
- `trade-agent-Shipments`
- `trade-agent-AgentTraces`

**Security rules:** the frontend never talks to Firestore directly - all reads/writes go through the
FastAPI backend using the service account. Lock client access down:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false;   // backend-only via service account; clients denied
    }
  }
}
```

---

## 5. Service accounts (backend runtime, local dev, build)

The backend uses one service account to read/write Firestore and call Vertex AI.
A **second, separate** identity builds the container; it is covered in 5b and is easy to miss because GCP creates it for you.

**Console:** IAM & Admin → **Service Accounts → Create** → name `trade-agent-platform-access`.

**CLI:**

```bash
gcloud iam service-accounts create trade-agent-platform-access \
  --display-name="trade-agent platform access" \
  --project=trade-agent-ff12a

SA="trade-agent-platform-access@trade-agent-ff12a.iam.gserviceaccount.com"

# Vertex AI (Gemini + embeddings)
gcloud projects add-iam-policy-binding trade-agent-ff12a \
  --member="serviceAccount:${SA}" --role="roles/aiplatform.user"

# Firestore read/write
gcloud projects add-iam-policy-binding trade-agent-ff12a \
  --member="serviceAccount:${SA}" --role="roles/datastore.user"

# Structured logging (trace surface) + minor logging read for operator debugging
gcloud projects add-iam-policy-binding trade-agent-ff12a \
  --member="serviceAccount:${SA}" --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding trade-agent-ff12a \
  --member="serviceAccount:${SA}" --role="roles/logging.viewer"
```

> `logging.viewer` is included so an operator can read the structured agent traces in Cloud Logging
> while debugging; the runtime itself only writes logs. It is the one grant beyond the runtime's strict
> needs (`DESIGN_DECISIONS.md` §8).

### 5a. Local development credentials

Cloud Run uses the attached service account automatically (no key needed in production). For **local
dev**, the backend authenticates via Application Default Credentials (`gcp/client.py` uses
`ApplicationDefault()`), so pick **one**:

- **Method A - gcloud ADC (recommended, no key file):** install the gcloud CLI and run
  `gcloud auth application-default login`. The SDK auto-detects the short-lived credentials it stores;
  nothing is downloaded and nothing can leak to git. Leave `GOOGLE_APPLICATION_CREDENTIALS` unset.
- **Method B - downloaded service-account key:** **Console:** the service account → **Keys → Add key →
  JSON**, saved as `backend/trade-agent-sa-key.json`, then point `GOOGLE_APPLICATION_CREDENTIALS` at it
  (Step 8). Use this if you prefer a dedicated SA identity or don't want the gcloud CLI locally.

> ⚠️ The key file (Method B) is already blocked by `.gitignore` (`*key*.json`, `*credentials*.json`).
> Never commit it. Method A avoids the key entirely and is the safer default.

### 5b. Build service account (narrow the auto-granted Editor)

`gcloud run deploy --source` runs the container build on Cloud Build as the **Compute Engine default service account** (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`), not the runtime SA from Step 5.
GCP creates that account with `roles/editor` attached, so out of the box the build identity holds near-full control of the project.
Replace it with `roles/run.builder`, the role Google scopes to source deploys - read the source object, read/write Artifact Registry, write logs, and nothing else:

```bash
COMPUTE_SA="486070629701-compute@developer.gserviceaccount.com"  # PROJECT_NUMBER-compute@...

# Grant the narrow role first so no window exists with neither, then remove Editor.
gcloud projects add-iam-policy-binding trade-agent-ff12a --project=trade-agent-ff12a \
  --member="serviceAccount:${COMPUTE_SA}" --role="roles/run.builder"

# roles/run.builder takes a couple of minutes to propagate; wait before the first deploy.
gcloud projects remove-iam-policy-binding trade-agent-ff12a --project=trade-agent-ff12a \
  --member="serviceAccount:${COMPUTE_SA}" --role="roles/editor"
```

Before removing Editor, confirm this account is not also serving as a runtime identity elsewhere - it is the default for Compute Engine, Cloud Functions, and any Cloud Run service deployed without an explicit `--service-account`.
Then prove the narrowed role with one real `backend/deploy.sh`: build-time and runtime identities are separate accounts, so a failed build cannot affect the running service, and Editor is one line to restore.

> To confirm which identity actually runs your builds: `gcloud builds list --region=us-central1 --format="table(id,status,serviceAccount)"`, then `gcloud builds describe <ID> --region=us-central1` for its source, steps, and image target. Pass `--region` - a region-less `gcloud builds list` returns nothing for Cloud Run source deploys.

The rationale for splitting the build and runtime identities is in [`DESIGN_DECISIONS.md`](https://github.com/yakyetilabs/trade-agent/blob/main/docs/DESIGN_DECISIONS.md) §12.

---

## 6. Artifact Registry (container images)

No manual step here. On the first `gcloud run deploy --source` (Step 9), Cloud Build creates the Artifact
Registry repository `cloud-run-source-deploy` in the service's region and pushes the image to it:

`us-central1-docker.pkg.dev/trade-agent-ff12a/cloud-run-source-deploy/trade-agent-backend`

The only prerequisite is the `artifactregistry` API from Step 2. A hand-named repository is unnecessary for
the source-deploy flow, so there is nothing to provision in advance.

---

## 7. Pinecone index (knowledge base)

Done in the Pinecone console (https://app.pinecone.io) - independent of GCP.

- **Name:** `trade-agent-hts-kb`
- **Dimension:** **768** (must match `gemini-embedding-001` called with `output_dimensionality=768`; the
  dimension is fixed at creation and cannot be changed later)
- **Metric:** `cosine`
- **Type/Cloud/Region:** Serverless, **AWS `us-east-1`**

Copy your **API key** (Pinecone console → API Keys) into `backend/.env` (Step 8).

---

## 8. Environment files

### `backend/.env` (copy from `backend/.env.example`)

```bash
GCP_PROJECT=trade-agent-ff12a
GCP_REGION=us-central1

# Vertex AI models (GA aliases)
VERTEX_PRIMARY_MODEL=gemini-2.5-flash
VERTEX_EVAL_MODEL=gemini-2.5-pro
VERTEX_EMBEDDING_MODEL=gemini-embedding-001
VERTEX_EMBEDDING_DIM=768

# Pinecone
PINECONE_API_KEY=pc-xxxxxxxxxxxxxxxxxxxx
PINECONE_INDEX=trade-agent-hts-kb

# Local dev only - Cloud Run uses the attached SA instead. Either point this at a downloaded key
# (Step 5a Method B), or leave it unset and use `gcloud auth application-default login` (Method A).
GOOGLE_APPLICATION_CREDENTIALS=./trade-agent-sa-key.json

# "local" relaxes CORS to http://localhost:5173; "production" locks to the Hosting origin
APP_ENV=local
```

### `frontend/.env.local` (optional; copy from `frontend/.env.local.example`)

The public demo needs no Firebase values. The only knob is the API base URL, and its defaults are
usually right: dev uses the same-origin `/api` (Vite proxy), production bakes the split-origin
`api.` subdomain from the committed `frontend/.env.production`.

```bash
# Only set to point local dev at a non-same-origin backend:
# VITE_API_BASE_URL=http://127.0.0.1:8000
```

---

## 9. Deploy targets (reference)

### Backend → Cloud Run

The `backend/deploy.sh` script runs a single deploy.
The image builds from `backend/Dockerfile`, not Cloud Run buildpacks: the Python buildpack doesn't install `uv` (the resolver) and its runtime registry doesn't carry every exact CPython patch, whereas a Dockerfile gives uv's lockfile-pinned installs, an exact interpreter, and a reviewable build.
`gcloud run deploy --source=backend` auto-prefers the Dockerfile when one is present (verified against the Cloud Run source-deploy docs), so the same `--source` command builds the image on Cloud Build with no separate `docker build`/`push` and no manual Artifact Registry step.
A `backend/.gcloudignore` keeps `.env` and the local `.venv` out of the source uploaded to Cloud Build (distinct from `.dockerignore`, which governs the image build context).
Key flags that preserve the architecture:

```bash
gcloud run deploy trade-agent-backend \
  --source=backend \
  --region=us-central1 \
  --service-account=trade-agent-platform-access@trade-agent-ff12a.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --min-instances=0 \
  --set-env-vars="GCP_PROJECT=trade-agent-ff12a,APP_ENV=production,..." \
  --project=trade-agent-ff12a
```

- `--allow-unauthenticated` is correct here: the API is a public synthetic-data demo bounded app-side
  (instance ceiling + Vertex quota + in-app per-IP rate limiter; `DESIGN_DECISIONS.md` §11), not by IAM.
  IAP or a Load Balancer would add fixed hourly cost and reintroduce CORS preflight failures, so the
  design omits both (`DESIGN_DECISIONS.md` §9, §11).
- `--min-instances=0` means no always-on instance (scale-to-zero). Trade-off: a ~5-15s cold start on the first request after idle.

### Frontend → Firebase Hosting

```bash
# from frontend/, after `pnpm build`
firebase deploy --only hosting:trade-agent-ff12a
```

Target bindings live in `.firebaserc` and `firebase.json` (built in the frontend phase).

**Split-origin API via a DNS-only `api.` subdomain (the current wiring - see `DESIGN_DECISIONS.md` §9).**
Production is split-origin.
The SPA is served from `trade-agent.samir.codes` (Firebase Hosting, Cloudflare-proxied) and calls the API cross-origin at `api.trade-agent.samir.codes`, a Cloudflare **grey-cloud (DNS-only)** `CNAME` to `ghs.googlehosted.com` backing a Cloud Run domain mapping.
DNS-only means no CDN sits on the API path, so the SSE reasoning stream is not buffered.
`firebase.json` therefore carries **no** `/api/**` rewrite - only the SPA fallback and asset caching:

```json
"hosting": {
  "public": "frontend/dist",
  "rewrites": [
    { "source": "**", "destination": "/index.html" }
  ]
}
```

Consequences.
The frontend build bakes the API origin via `VITE_API_BASE_URL` in `frontend/.env.production` (`https://api.trade-agent.samir.codes/api`).
The cross-origin call means CORS is back on the production path, so the backend must allowlist the frontend origins via `PROD_FRONTEND_ORIGINS` (set in `deploy.sh`, read by `resolve_cors_origins`, applied by `CORSMiddleware`).
API responses still carry `Cache-Control: no-store`, since the frontend origin remains CDN-fronted.
Local dev stays same-origin via the Vite dev-server proxy, so only production needs the cross-origin grant.
This is a DNS record plus a middleware allowlist, not a load balancer or IAP, so it still adds no fixed cost and respects the no-IAP/no-LB rule.

**Why the pivot (was same-origin):** the original wiring proxied `/api/**` through the Hosting CDN for a zero-CORS same-origin path, which is ideal for request/response, but the CDN buffered the later SSE stream, so the streaming path was moved off the CDN.
See `DESIGN_DECISIONS.md` §9 "The split-origin pivot".

---

## 10. Post-setup verification

- [ ] `gcloud config get-value project` → `trade-agent-ff12a`
- [ ] All 6 APIs from Step 2 show **Enabled** in the console
- [ ] Firestore database exists in `us-central1` with the three `trade-agent-*` collections
- [ ] The service account has the 4 roles from Step 5
- [ ] Local credentials ready: `gcloud auth application-default login` done (Method A), **or** `backend/trade-agent-sa-key.json` exists and is **not** tracked by git (Method B; `git status` clean)
- [ ] Pinecone index `trade-agent-hts-kb` is **768-dim, cosine, AWS us-east-1**
- [ ] `backend/.env` populated (`frontend/.env.local` is optional)

Once these pass, deploy with Step 9 (backend `deploy.sh`, then the Hosting deploy).
