#!/usr/bin/env bash
set -euo pipefail

PROJECT="vacant-lot-detection"
REGION="us-east4"
REPO="vacant-lot"
SERVICE="vacant-lot-app"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/app"

echo "==> Building image with Cloud Build..."
gcloud builds submit --tag "$IMAGE" --project "$PROJECT"

echo "==> Deploying to Cloud Run..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8000 \
  --project "$PROJECT"

echo "==> Done."
gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)'
