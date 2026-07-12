#!/usr/bin/env bash
# Deploy the backend to Cloud Run. Cloud Build builds backend/Dockerfile (gcloud auto-prefers
# it over buildpacks) and pushes to the auto-created `cloud-run-source-deploy` Artifact
# Registry repo. The API is a public synthetic-data demo (no sign-in), so the service is
# --allow-unauthenticated and there is deliberately no IAP / Load Balancer; spend is capped
# by the instance ceiling below plus the in-app per-IP rate limiter.
set -euo pipefail

# Run from backend/ regardless of the caller's cwd (so `--source=.` is this directory).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Config (all env-overridable) ---------------------------------------------------------
PROJECT="${GCP_PROJECT:-trade-agent-ff12a}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${SERVICE_NAME:-trade-agent-backend}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-trade-agent-platform-access@${PROJECT}.iam.gserviceaccount.com}"
PINECONE_SECRET="${PINECONE_SECRET:-trade-agent-pinecone-api-key}"

# Resource tuning for a heavy AI request (langchain + grpc imports + model calls).
# max-instances x concurrency is the TRUE parallel-run ceiling on Cloud Run (unlike Lambda,
# where reserved concurrency alone caps it): 2 x 1 = at most 2 agent runs in flight, the
# public demo's hard spend ceiling (docs/DESIGN_DECISIONS.md §11). concurrency=1 also gives
# each run its own instance, so one run's memory spike cannot OOM another's request.
# --min-instances=0 keeps idle cost at $0.
MEMORY="${MEMORY:-1Gi}"
CPU="${CPU:-1}"
CONCURRENCY="${CONCURRENCY:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-2}"
TIMEOUT="${TIMEOUT:-300}"

# The CORS allow-list: every browser origin the frontend is served from. Split-origin
# deploy (docs/DESIGN_DECISIONS.md §9) - the frontend calls the api. subdomain from the
# custom domain plus Firebase's two default hostnames, each a distinct browser origin
# under the CORS spec. The old trade-agent.samir.codes origin stays allowlisted during
# the rebrand cutover; drop it once the tradeops-ai domain is verified live.
PROD_FRONTEND_ORIGINS="${PROD_FRONTEND_ORIGINS:-https://tradeops-ai.samir.codes,https://trade-agent.samir.codes,https://trade-agent-ff12a.web.app,https://trade-agent-ff12a.firebaseapp.com}"

# --- Preflight: fail fast, and NEVER block on a prompt --------------------------------------
# --quiet disables interactive prompts so a not-yet-enabled API can't leave the script hanging
# on a hidden "enable and retry? (y/N)" read (that redirect-swallowed prompt is exactly what
# stalled an early run). Each check prints its own actionable next step instead.
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" --quiet | grep -q .; then
  echo "ERROR: no active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" --project="$PROJECT" --quiet >/dev/null 2>&1; then
  echo "ERROR: runtime service account '$SERVICE_ACCOUNT' does not exist. Create it + grant its" >&2
  echo "       roles once (GCP_SETUP.md §5): aiplatform.user, datastore.user, logging.logWriter," >&2
  echo "       logging.viewer, and secretmanager.secretAccessor on the secret." >&2
  exit 1
fi
if ! gcloud services list --enabled --project="$PROJECT" --quiet \
     --format="value(config.name)" | grep -qx "secretmanager.googleapis.com"; then
  echo "ERROR: the Secret Manager API is not enabled on '$PROJECT'. Enable it once:" >&2
  echo "  gcloud services enable secretmanager.googleapis.com --project=$PROJECT" >&2
  exit 1
fi
if ! gcloud secrets describe "$PINECONE_SECRET" --project="$PROJECT" --quiet >/dev/null 2>&1; then
  cat >&2 <<EOF
ERROR: Secret '$PINECONE_SECRET' not found in project '$PROJECT'. One-time setup (the key
value comes from your local backend/.env; PINECONE_API_KEY must be exported for the middle line):

  gcloud secrets create $PINECONE_SECRET --project=$PROJECT --replication-policy=automatic
  printf '%s' "\$PINECONE_API_KEY" | gcloud secrets versions add $PINECONE_SECRET --project=$PROJECT --data-file=-
  gcloud secrets add-iam-policy-binding $PINECONE_SECRET --project=$PROJECT \\
    --member="serviceAccount:$SERVICE_ACCOUNT" --role=roles/secretmanager.secretAccessor
EOF
  exit 1
fi

# Env vars go through a YAML file, not --set-env-vars: the origins value contains commas,
# which are gcloud's list delimiters and would corrupt an inline --set-env-vars.
# Secrets stay out of this file - the Pinecone key is mounted from Secret Manager below.
ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT
cat > "$ENV_FILE" <<EOF
APP_ENV: production
GCP_PROJECT: "$PROJECT"
GCP_REGION: "$REGION"
PROD_FRONTEND_ORIGINS: "$PROD_FRONTEND_ORIGINS"
EOF

echo "==> Deploying '$SERVICE' to Cloud Run (project $PROJECT, region $REGION)"
gcloud run deploy "$SERVICE" \
  --source=. \
  --project="$PROJECT" \
  --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances="$MAX_INSTANCES" \
  --memory="$MEMORY" \
  --cpu="$CPU" \
  --concurrency="$CONCURRENCY" \
  --timeout="$TIMEOUT" \
  --env-vars-file="$ENV_FILE" \
  --set-secrets="PINECONE_API_KEY=${PINECONE_SECRET}:latest"

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --format='value(status.url)')"
echo "==> Deployed: $URL"
echo "    Smoke test (public API, no token):"
echo "      curl -sS $URL/health && curl -sS $URL/api/vendors"
