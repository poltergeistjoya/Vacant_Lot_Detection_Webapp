#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
set -a; source deploy.env; set +a
: "${GCP_PROJECT:?set it in deploy.env}" "${GCP_REGION:?set it in deploy.env}" "${ARTIFACT_REPO:?set it in deploy.env}"
: "${CLOUD_RUN_SERVICE:?set it in deploy.env}" "${TILE_STORE_BUCKET:?set it in deploy.env}"

MEMORY="${CLOUD_RUN_MEMORY:-512Mi}"
MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-1}"
MAX_INSTANCES="${CLOUD_RUN_MAX_INSTANCES:-3}"
WORKERS="${WEB_WORKERS:-2}"

IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$ARTIFACT_REPO/app"

echo "==> Running tests..."
npm run test:all

echo "==> Building image with Cloud Build..."
gcloud builds submit --tag "$IMAGE" --project "$GCP_PROJECT"

echo "==> Deploying to Cloud Run..."
gcloud run deploy "$CLOUD_RUN_SERVICE" \
  --image "$IMAGE" \
  --platform managed \
  --region "$GCP_REGION" \
  --allow-unauthenticated \
  --port 8000 \
  --memory "$MEMORY" \
  --min-instances "$MIN_INSTANCES" \
  --max-instances "$MAX_INSTANCES" \
  --set-env-vars "TILE_STORE_BUCKET=$TILE_STORE_BUCKET,WEB_CONCURRENCY=$WORKERS" \
  --project "$GCP_PROJECT"

echo "==> Done."
gcloud run services describe "$CLOUD_RUN_SERVICE" --region "$GCP_REGION" --project "$GCP_PROJECT" --format='value(status.url)'
