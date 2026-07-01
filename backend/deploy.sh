#!/usr/bin/env bash
# Deploy the backend to Cloud Run. Cloud Build builds backend/Dockerfile (gcloud auto-prefers
# it over buildpacks) and pushes to the auto-created `cloud-run-source-deploy` Artifact
# Registry repo. Authorization is app-level (Firebase JWT + allowlist), so the service is
# --allow-unauthenticated and there is deliberately no IAP / Load Balancer.
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

# Resource tuning for a heavy AI request (langchain + grpc imports + model calls). Modest
# --concurrency so many in-flight agent runs scale out to new instances rather than OOM one;
# --max-instances caps the cost/quota blast radius; --min-instances=0 keeps idle cost at $0.
MEMORY="${MEMORY:-1Gi}"
CPU="${CPU:-1}"
CONCURRENCY="${CONCURRENCY:-8}"
MAX_INSTANCES="${MAX_INSTANCES:-4}"
TIMEOUT="${TIMEOUT:-300}"

# TRADE_AGENT_ANALYST_SCOPES is the identity allowlist + vendor-scope map (not a secret, but
# we don't bake a personal email into a committed script). Take it from the environment, or
# pull just that one line from backend/.env - never source .env wholesale (it holds secrets).
if [[ -z "${TRADE_AGENT_ANALYST_SCOPES:-}" && -f .env ]]; then
  TRADE_AGENT_ANALYST_SCOPES="$(grep -E '^TRADE_AGENT_ANALYST_SCOPES=' .env | tail -1 | cut -d= -f2-)"
fi
if [[ -z "${TRADE_AGENT_ANALYST_SCOPES:-}" ]]; then
  echo "ERROR: TRADE_AGENT_ANALYST_SCOPES is not set (export it or add it to backend/.env)." >&2
  echo "       Format: email=V-001,V-002;email2=*   (a lone * grants all vendors / admin)." >&2
  exit 1
fi

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
  echo "       logging.viewer, firebaseauth.admin, and secretmanager.secretAccessor on the secret." >&2
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

# Env vars go through a YAML file, not --set-env-vars: the scopes value contains commas and
# semicolons, which are gcloud's list delimiters and would corrupt an inline --set-env-vars.
# Secrets stay out of this file - the Pinecone key is mounted from Secret Manager below.
ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT
cat > "$ENV_FILE" <<EOF
APP_ENV: production
GCP_PROJECT: "$PROJECT"
GCP_REGION: "$REGION"
TRADE_AGENT_ANALYST_SCOPES: "$TRADE_AGENT_ANALYST_SCOPES"
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
echo "    Smoke test (needs a Firebase ID token for an allowlisted analyst):"
echo "      curl -sS -H \"Authorization: Bearer \$ID_TOKEN\" $URL/api/me"
