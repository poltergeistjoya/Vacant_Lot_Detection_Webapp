#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
: "${GCP_PROJECT:?set it in .env}" "${GCP_REGION:?set it in .env}" "${ARTIFACT_REPO:?set it in .env}"
: "${CLOUD_RUN_SERVICE:?set it in .env}" "${TILE_STORE_BUCKET:?set it in .env}"

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
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars "TILE_STORE_BUCKET=$TILE_STORE_BUCKET" \
  --project "$GCP_PROJECT"

echo "==> Done."
gcloud run services describe "$CLOUD_RUN_SERVICE" --region "$GCP_REGION" --project "$GCP_PROJECT" --format='value(status.url)'
