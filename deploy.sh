#!/usr/bin/env bash
set -euo pipefail

PROJECT="vacant-lot-detection"
REGION="us-east4"
REPO="vacant-lot"
SERVICE="vacant-lot-app"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/app"
# GCS bucket for pre-rendered tiles
TILE_STORE_BUCKET="vacant-lot-tiles"
# Public URL for PMTiles archives (browser fetches directly via range requests)
PMTILES_BASE_URL="https://storage.googleapis.com/${TILE_STORE_BUCKET}/pmtiles"

echo "==> Running tests..."
npm run test:all

echo "==> Building image with Cloud Build..."
gcloud builds submit --tag "$IMAGE" --project "$PROJECT"

echo "==> Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8000 \
  --memory 1Gi \
  --min-instances 1 \
  --set-env-vars "TILE_STORE_BUCKET=$TILE_STORE_BUCKET" \
  --project "$PROJECT"

echo "==> Done."
gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)'
