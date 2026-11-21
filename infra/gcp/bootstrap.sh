#!/usr/bin/env bash
# Idempotent GCP bootstrap for one Bool environment (design doc §3.2, task S1-02).
#
# Usage: infra/gcp/bootstrap.sh <project-id> <staging|prod>
#
# Creates (skipping anything that already exists):
#   - required APIs
#   - Artifact Registry Docker repo "bool" in europe-west3
#   - service accounts: bool-api, bool-worker (runtime), bool-deployer (GitHub Actions)
#   - Workload Identity Federation for GitHub Actions (no service-account keys)
#   - empty Secret Manager secrets (values are added separately; never in the repo)
set -euo pipefail

PROJECT_ID="${1:?usage: bootstrap.sh <project-id> <staging|prod>}"
ENV="${2:?usage: bootstrap.sh <project-id> <staging|prod>}"
[[ "$ENV" == "staging" || "$ENV" == "prod" ]] || { echo "env must be staging or prod" >&2; exit 1; }

REGION="europe-west3"
GITHUB_REPO="2alexg/booljob-me"
AR_REPO="bool"
POOL="github"
PROVIDER="github-oidc"

g() { gcloud --project "$PROJECT_ID" --quiet "$@"; }
exists() { g "$@" >/dev/null 2>&1; }

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
echo "==> $PROJECT_ID ($PROJECT_NUMBER), env=$ENV, region=$REGION"

echo "==> Enabling APIs"
g services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com

echo "==> Artifact Registry"
exists artifacts repositories describe "$AR_REPO" --location "$REGION" ||
  g artifacts repositories create "$AR_REPO" \
    --repository-format docker --location "$REGION" \
    --description "Bool container images"

echo "==> Service accounts"
for sa in bool-api bool-worker bool-deployer; do
  exists iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" ||
    g iam service-accounts create "$sa" --display-name "$sa"
done
SA_API="bool-api@$PROJECT_ID.iam.gserviceaccount.com"
SA_WORKER="bool-worker@$PROJECT_ID.iam.gserviceaccount.com"
SA_DEPLOYER="bool-deployer@$PROJECT_ID.iam.gserviceaccount.com"

bind_project() { # member role
  g projects add-iam-policy-binding "$PROJECT_ID" \
    --member "$1" --role "$2" --condition None >/dev/null
}

# Only the worker calls Vertex AI.
bind_project "serviceAccount:$SA_WORKER" roles/aiplatform.user
# The deployer pushes images and deploys Cloud Run services.
bind_project "serviceAccount:$SA_DEPLOYER" roles/run.developer
g artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$REGION" \
  --member "serviceAccount:$SA_DEPLOYER" --role roles/artifactregistry.writer >/dev/null
# The deployer may deploy services that run as the runtime accounts (and nothing else).
for sa in "$SA_API" "$SA_WORKER"; do
  g iam service-accounts add-iam-policy-binding "$sa" \
    --member "serviceAccount:$SA_DEPLOYER" --role roles/iam.serviceAccountUser >/dev/null
done

echo "==> Workload Identity Federation for GitHub Actions"
exists iam workload-identity-pools describe "$POOL" --location global ||
  g iam workload-identity-pools create "$POOL" --location global \
    --display-name "GitHub Actions"

# staging: any ref of the repo; prod: only the main branch.
CONDITION="assertion.repository == '$GITHUB_REPO'"
[[ "$ENV" == "prod" ]] && CONDITION="$CONDITION && assertion.ref == 'refs/heads/main'"

exists iam workload-identity-pools providers describe "$PROVIDER" \
  --workload-identity-pool "$POOL" --location global ||
  g iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --workload-identity-pool "$POOL" --location global \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "$CONDITION"

g iam service-accounts add-iam-policy-binding "$SA_DEPLOYER" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$GITHUB_REPO" \
  >/dev/null

echo "==> Secrets (containers only)"
# secret-name:runtime-accounts-that-may-read-it
SECRETS=(
  "internal-secret:api"
  "database-url:api,worker"
  "supabase-service-role-key:api,worker"
  "qstash-token:api,worker"
  "qstash-current-signing-key:worker"
  "qstash-next-signing-key:worker"
  "upstash-redis-url:api"
  "upstash-redis-token:api"
  "telegram-bot-token:api,worker"
  "google-maps-api-key:worker"
)
for entry in "${SECRETS[@]}"; do
  name="${entry%%:*}"
  readers="${entry#*:}"
  exists secrets describe "$name" ||
    g secrets create "$name" --replication-policy user-managed --locations "$REGION"
  for r in ${readers//,/ }; do
    sa_var="SA_${r^^}"
    g secrets add-iam-policy-binding "$name" \
      --member "serviceAccount:${!sa_var}" --role roles/secretmanager.secretAccessor >/dev/null
  done
done

# internal-secret is generated here; every other value is added by hand.
if ! g secrets versions list internal-secret --limit 1 --format 'value(name)' | grep -q .; then
  openssl rand -base64 48 | tr -d '\n' | g secrets versions add internal-secret --data-file -
  echo "    generated internal-secret"
fi

cat <<EOF

==> Done. Add these as GitHub Actions variables for the "$ENV" environment:
  GCP_PROJECT_ID=$PROJECT_ID
  GCP_REGION=$REGION
  GCP_WORKLOAD_IDENTITY_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER
  GCP_DEPLOYER_SA=$SA_DEPLOYER
EOF
