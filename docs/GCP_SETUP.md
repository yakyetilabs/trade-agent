# GCP & Pinecone Setup — Manual Runbook

This is the step-by-step manual setup for the `trade-agent` stack. Per the project's IaC posture — a
deliberate design decision to ship with **no managed IaC** for the initial build — there is **no
Terraform**: console setup plus single-line CLI deploy scripts only.

Everything lives in **one** project — `trade-agent-demo`. A Firebase project *is* a GCP project,
so Firebase Auth, Firestore, Cloud Run, and Firebase Hosting all share it. This is what makes the
Firebase ID-token audience (`= <project-id>`) line up with the backend verifier.

> 💸 **Budget reminder.** The fixed + idle footprint is $0 (Cloud Run scale-to-zero, Firestore/Auth/
> Hosting free tiers, Pinecone Starter). Vertex AI inference + embeddings are usage-metered, funded by
> the $200 GCP trial credits — cents at demo volume. This is the project's documented budget posture.

---

## 0. Prerequisites

Local tooling:

```bash
gcloud --version        # Google Cloud CLI
firebase --version      # Firebase CLI  (npm i -g firebase-tools)
uv --version            # Python 3.12 package manager
pnpm --version          # Node package manager
```

Accounts you already have: a Google Cloud account (with the $200 trial credits) and a Pinecone account.

Conventions used below:

- **Project ID:** `trade-agent-demo`
- **GCP region:** `us-central1`
- **Resource prefix:** every GCP resource is named with the `trade-agent-` prefix (a non-negotiable project naming convention for account-level isolation).

---

## 1. Create the project & link billing

**Console:** https://console.cloud.google.com → project picker → **New Project** → name `trade-agent-demo`.
Then **Billing** → link your billing account (the trial credits live here; scale-to-zero keeps the bill at $0).

**CLI equivalent:**

```bash
gcloud projects create trade-agent-demo --name="trade-agent-demo"
gcloud config set project trade-agent-demo
# Link billing (find your account id with: gcloud billing accounts list)
gcloud billing projects link trade-agent-demo --billing-account=XXXXXX-XXXXXX-XXXXXX
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
  iamcredentials.googleapis.com \
  identitytoolkit.googleapis.com \
  --project=trade-agent-demo
```

- `run` — Cloud Run (backend container)
- `aiplatform` — Vertex AI (Gemini 2.5 Flash/Pro + `gemini-embedding-001`)
- `firestore` — state + audit store
- `artifactregistry` — container image storage (Container Registry / `gcr.io` is retired; use Artifact Registry)
- `cloudbuild` — image build during `gcloud run deploy --source`
- `identitytoolkit` — Firebase Authentication backend

---

## 3. Add Firebase to the project

**Console:** https://console.firebase.google.com → **Add project** → select the existing `trade-agent-demo`
GCP project (do **not** create a new one). Accept the Spark (free) plan.

### 3a. Enable Authentication

Firebase console → **Build → Authentication → Get started** → enable a sign-in provider:

- **Email/Password** (simplest for a demo), and/or
- **Google** (one-click sign-in).

> The backend authorizes by email against the in-memory allowlist, so whichever provider you pick must
> surface a verified `email` claim in the ID token. Email/Password and Google both do.

### 3b. Register the web app (frontend config)

Firebase console → **Project settings → General → Your apps → Web (`</>`)** → register an app named
`trade-agent-web`. Copy the `firebaseConfig` values — these go into `frontend/.env.local` (Step 8).

---

## 4. Firestore (Native mode) + collections

**Console:** Firebase or GCP console → **Firestore → Create database** →
**Native mode** → location `us-central1` (single-region, free-tier eligible) → **Production mode** rules.

There is one free Firestore database per project; create it in `us-central1` to match Cloud Run.

Create the three collections (they can also be created lazily by the seed scripts, but creating them now
makes the console navigable):

- `trade-agent-Vendors`
- `trade-agent-Shipments`
- `trade-agent-AgentTraces`

**Security rules:** the frontend never talks to Firestore directly — all reads/writes go through the
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

## 5. Service account (backend runtime + local dev)

The backend uses one service account to verify Firebase tokens (Admin SDK), read/write Firestore, and
call Vertex AI.

**Console:** IAM & Admin → **Service Accounts → Create** → name `trade-agent-platform-access`.

**CLI:**

```bash
gcloud iam service-accounts create trade-agent-platform-access \
  --display-name="trade-agent platform access" \
  --project=trade-agent-demo

SA="trade-agent-platform-access@trade-agent-demo.iam.gserviceaccount.com"

# Vertex AI (Gemini + embeddings)
gcloud projects add-iam-policy-binding trade-agent-demo \
  --member="serviceAccount:${SA}" --role="roles/aiplatform.user"

# Firestore read/write
gcloud projects add-iam-policy-binding trade-agent-demo \
  --member="serviceAccount:${SA}" --role="roles/datastore.user"

# Structured logging (trace surface) + minor logging read for operator debugging
gcloud projects add-iam-policy-binding trade-agent-demo \
  --member="serviceAccount:${SA}" --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding trade-agent-demo \
  --member="serviceAccount:${SA}" --role="roles/logging.viewer"

# Firebase token verification (Admin SDK)
gcloud projects add-iam-policy-binding trade-agent-demo \
  --member="serviceAccount:${SA}" --role="roles/firebaseauth.admin"
```

> The `logging.viewer` grant is the deliberately-not-least-privilege bit called out in
> `DESIGN_DECISIONS.md` §8 — minor logging read for rapid operator debugging.

### 5a. Key for local development only

Cloud Run uses the attached service account automatically (no key needed in production). For **local
dev**, download a key:

**Console:** the service account → **Keys → Add key → JSON**. Save it as
`backend/trade-agent-sa-key.json`.

> ⚠️ This file is already blocked by `.gitignore` (`*key*.json`, `*credentials*.json`). Never commit it.
> Point `GOOGLE_APPLICATION_CREDENTIALS` at it locally (Step 8).

---

## 6. Artifact Registry (container images)

**CLI:**

```bash
gcloud artifacts repositories create trade-agent-images \
  --repository-format=docker \
  --location=us-central1 \
  --description="trade-agent backend container images" \
  --project=trade-agent-demo
```

The backend image will be pushed to
`us-central1-docker.pkg.dev/trade-agent-demo/trade-agent-images/trade-agent-backend`.

---

## 7. Pinecone index (knowledge base)

Done in the Pinecone console (https://app.pinecone.io) — independent of GCP.

- **Name:** `trade-agent-hts-kb`
- **Dimension:** **768** (must match `gemini-embedding-001` called with `output_dimensionality=768`; the
  dimension is fixed at creation and cannot be changed later)
- **Metric:** `cosine`
- **Type/Cloud/Region:** Serverless, **AWS `us-east-1`** (the only region the free Starter plan supports)

Copy your **API key** (Pinecone console → API Keys) into `backend/.env` (Step 8).

> ⚠️ Free Starter indexes **auto-pause after ~3 weeks of inactivity**. If the demo has been idle a long
> time, the first query may need a reactivation / re-ingest (`uv run python -m scripts.ingest_kb`).

---

## 8. Environment files

### `backend/.env` (copy from `backend/.env.example`)

```bash
GCP_PROJECT=trade-agent-demo
GCP_REGION=us-central1

# Vertex AI models (GA aliases)
VERTEX_PRIMARY_MODEL=gemini-2.5-flash
VERTEX_EVAL_MODEL=gemini-2.5-pro
VERTEX_EMBEDDING_MODEL=gemini-embedding-001
VERTEX_EMBEDDING_DIM=768

# Pinecone
PINECONE_API_KEY=pc-xxxxxxxxxxxxxxxxxxxx
PINECONE_INDEX=trade-agent-hts-kb

# $0 zero-trust allowlist (comma-separated, lowercased at boot)
TRADE_AGENT_ALLOWED_USERS=your-email@gmail.com,tester@gmail.com

# Local dev only — Cloud Run uses the attached SA instead
GOOGLE_APPLICATION_CREDENTIALS=./trade-agent-sa-key.json

# "local" relaxes CORS to http://localhost:5173; "production" locks to the Hosting origin
APP_ENV=local
```

### `frontend/.env.local` (copy from `frontend/.env.local.example`)

From the Step 3b web-app config:

```bash
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=trade-agent-demo.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=trade-agent-demo
VITE_FIREBASE_APP_ID=...
# Cloud Run service URL (filled in after Step 9), or http://127.0.0.1:8000 for local
VITE_API_BASE_URL=http://127.0.0.1:8000
```

---

## 9. Deploy targets (reference — scripts come in later phases)

### Backend → Cloud Run

The `backend/deploy.sh` script (built in a later phase) will run a single deploy. Key flags that preserve
the architecture:

```bash
gcloud run deploy trade-agent-backend \
  --source=backend \
  --region=us-central1 \
  --service-account=trade-agent-platform-access@trade-agent-demo.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --min-instances=0 \
  --set-env-vars="GCP_PROJECT=trade-agent-demo,APP_ENV=production,..." \
  --project=trade-agent-demo
```

- `--allow-unauthenticated` is correct here: authorization is **app-level** (Firebase JWT + allowlist),
  not IAM. This is why we deliberately do **not** add IAP / a Load Balancer (a fixed-cost component the
  $0 budget decision rules out).
- `--min-instances=0` keeps the idle cost at $0. Trade-off: a ~5–15s cold start on the first request.

### Frontend → Firebase Hosting

```bash
# from frontend/, after `pnpm build`
firebase deploy --only hosting:trade-agent-demo
```

Target bindings live in `.firebaserc` and `firebase.json` (built in the frontend phase).

---

## 10. Post-setup verification

- [ ] `gcloud config get-value project` → `trade-agent-demo`
- [ ] All 7 APIs from Step 2 show **Enabled** in the console
- [ ] Firestore database exists in `us-central1` with the three `trade-agent-*` collections
- [ ] A test user can sign up via the Firebase Auth provider you enabled
- [ ] The service account has the 5 roles from Step 5
- [ ] `backend/trade-agent-sa-key.json` exists locally and is **not** tracked by git (`git status` clean)
- [ ] Pinecone index `trade-agent-hts-kb` is **768-dim, cosine, AWS us-east-1**
- [ ] `backend/.env` and `frontend/.env.local` populated

Once these pass, proceed to **Phase 1** (backend skeleton + security boundary).
