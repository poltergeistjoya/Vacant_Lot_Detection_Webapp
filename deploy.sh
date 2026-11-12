#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
source scripts/env.sh
require_env GCP_PROJECT GCP_REGION ARTIFACT_REPO CLOUD_RUN_SERVICE TILE_STORE_BUCKET

IMAGE="$GCP_REGION-docker.pkg.dev/$GCP_PROJECT/$ARTIFACT_REPO/app"
# Public URL for PMTiles archives (browser fetches directly via range requests)
PMTILES_BASE_URL="https://storage.googleapis.com/${TILE_STORE_BUCKET}/pmtiles"

echo "==> Running tests..."
npm run test:all

echo "==> Checking PMTiles archives on GCS..."
./scripts/check_pmtiles_gcs.sh

echo "==> Building image with Cloud Build..."
gcloud builds submit --config cloudbuild.yaml \
  --substitutions "_IMAGE=$IMAGE,_PMTILES_BASE_URL=$PMTILES_BASE_URL" \
  --project "$GCP_PROJECT"

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
