#!/usr/bin/env bash
# Run the Locust soak test (scripts/soak_test.py) against the service in deploy.env.
# Resolves the deterministic Cloud Run URL, shows it, and waits for confirmation (costs money).
#
# Usage:
#   ./scripts/soak_test.sh smoke            # 1 min, 5 users
#   ./scripts/soak_test.sh ramp             # 5/20/50/100 users, 3 min each
#   SOAK_USERS=30 SOAK_MINUTES=10 ./scripts/soak_test.sh flat
#   ./scripts/soak_test.sh smoke https://other-host   # explicit target override
set -euo pipefail

cd "$(dirname "$0")/.."
set -a; source deploy.env; set +a

MODE="${1:?mode: smoke | ramp | flat}"
if [[ -n "${2:-}" ]]; then
  URL="$2"
else
  NUM=$(gcloud projects describe "$GCP_PROJECT" --format='value(projectNumber)')
  URL="https://${CLOUD_RUN_SERVICE}-${NUM}.${GCP_REGION}.run.app"
fi

echo "Mode:   $MODE"
echo "Target: $URL"
echo "Config: $(gcloud run services describe "$CLOUD_RUN_SERVICE" --region "$GCP_REGION" --project "$GCP_PROJECT" \
  --format='value(spec.template.spec.containers[0].resources.limits.memory,spec.template.metadata.annotations."autoscaling.knative.dev/maxScale")')"
read -r -p "This sends real traffic and costs money. Continue? [y/N] " ok
[[ "$ok" == "y" ]] || exit 1

SOAK_MODE="$MODE" uv run locust -f scripts/soak_test.py --headless --host "$URL"
